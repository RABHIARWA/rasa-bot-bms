# actions.py - Complete with notifications insertion

import os
import re
import json
import uuid
import base64
import boto3
import pymysql
import requests
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, ActionExecutionRejected
from sqlalchemy import create_engine, text
import smtplib, ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from email.mime.image import MIMEImage

import openai
from openai import OpenAI

# OpenAI Client

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
openai.api_key = os.getenv("OPENAI_API_KEY")

# OneSignal Configuration
ONESIGNAL_APP_ID = os.getenv("ONESIGNAL_APP_ID")
ONE_SIGNAL_API_KEY = os.getenv("ONE_SIGNAL_API_KEY")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Building Bot")
EMAIL_SENDER = os.getenv("EMAIL_SENDER", SMTP_USERNAME)
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "smtp").lower()  # 'smtp' or 'onesignal'

# Database Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_DATABASE = os.getenv("DB_DATABASE", "bms_ged")
DB_USERNAME = os.getenv("DB_USERNAME", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
# ==================== HELPER FUNCTIONS ====================
def get_db_engine():
    """Create and return database engine with credentials from env"""
    connection_string = f"mysql+pymysql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_DATABASE}"
    return create_engine(connection_string)

def parse_data_url(data_url: str):
    m = re.match(r"^data:(image/\w+);base64,(.+)$", data_url)
    if not m:
        raise ValueError("Invalid image data URL")
    mime, b64 = m.groups()
    return mime, base64.b64decode(b64)

# ==================== IMPROVED B2 UPLOAD FUNCTION ====================

def b2_client():
    """Create B2 client with validation"""
    endpoint = os.getenv("B2_ENDPOINT")
    key_id = os.getenv("B2_KEY_ID")
    app_key = os.getenv("B2_APP_KEY")
    
    # Validate credentials
    if not all([endpoint, key_id, app_key]):
        missing = []
        if not endpoint: missing.append("B2_ENDPOINT")
        if not key_id: missing.append("B2_KEY_ID")
        if not app_key: missing.append("B2_APP_KEY")
        raise ValueError(f"Missing B2 credentials: {', '.join(missing)}")
    
    # Create client with timeout config
    config = boto3.session.Config(
        connect_timeout=10,
        read_timeout=30,
        retries={'max_attempts': 2}
    )
    
    return boto3.client(
        "s3",
        endpoint_url=f"https://{endpoint}",
        aws_access_key_id=key_id,
        aws_secret_access_key=app_key,
        region_name="eu-central-003",
        config=config
    )


def upload_to_b2(data_url: str, bucket: str, key_prefix="complaints/"):
    """Upload image to B2 with better error handling"""
    try:
        # Parse image
        mime, blob = parse_data_url(data_url)
        blob_size_mb = len(blob) / (1024 * 1024)
        
        print(f"[B2] Uploading image: {mime}, size: {blob_size_mb:.2f} MB")
        
        # Check size (max 10MB)
        if blob_size_mb > 10:
            raise ValueError(f"Image too large: {blob_size_mb:.2f} MB (max 10 MB)")
        
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(mime, "bin")
        key = f"{key_prefix}{datetime.utcnow():%Y/%m}/{uuid.uuid4().hex}.{ext}"
        
        # Upload with retry
        s3 = b2_client()
        
        print(f"[B2] Uploading to bucket: {bucket}, key: {key}")
        
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=blob,
            ContentType=mime
        )
        
        public_url = f"https://{bucket}.s3.eu-central-003.backblazeb2.com/{key}"
        presigned = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=int(timedelta(hours=1).total_seconds())
        )
        
        print(f"[B2] Upload successful: {public_url}")
        return public_url, presigned, key
        
    except ValueError as ve:
        # Re-raise validation errors
        raise ve
    except Exception as e:
        # Log detailed error
        print(f"[B2 ERROR] Type: {type(e).__name__}")
        print(f"[B2 ERROR] Message: {str(e)}")
        import traceback
        traceback.print_exc()
        raise Exception(f"B2 upload failed: {str(e)}")
    
def get_sentiment_score(text_val: str):
    prompt = f"Rate the sentiment of this text from -1 (very negative) to +1 (very positive): {text_val}"
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=5,
            temperature=0
        )
        score = float(response.choices[0].message.content.strip())
        return max(min(score, 1), -1)
    except Exception as e:
        print("Sentiment error:", e)
        return 0

def send_smtp_email(to_email: str, subject: str, html_body: str, text_fallback: str = None, image_url: str = None):
    """
    Send email via Gmail SMTP (STARTTLS). Supports embedding ONE inline image from a public URL.
    Returns {'ok': True} or {'error': '...'}.
    """
    if not EMAIL_ENABLED:
        print("[EMAIL] Disabled by EMAIL_ENABLED=false")
        return {"error": "email_disabled"}

    if not (SMTP_USERNAME and SMTP_PASSWORD):
        print("[ERR] Missing SMTP credentials in env.")
        return {"error": "missing_smtp_credentials"}

    try:
        msg = MIMEMultipart("related")   # related = allows inline images
        msg["Subject"] = subject
        msg["From"] = formataddr((SMTP_FROM_NAME, EMAIL_SENDER))
        msg["To"] = to_email

        # Build alternative (plain + HTML) container
        alt = MIMEMultipart("alternative")
        msg.attach(alt)

        # Plain text fallback
        if not text_fallback:
            text_fallback = re.sub(r"<[^>]+>", "", html_body or "")
        alt.attach(MIMEText(text_fallback, "plain", "utf-8"))

        # If we have an image_url AND the HTML references cid:complaint_photo,
        # try to fetch and embed the image
        embedded = False
        if image_url and "cid:complaint_photo" in (html_body or ""):
            try:
                r = requests.get(image_url, timeout=15)
                r.raise_for_status()
                img_part = MIMEImage(r.content)
                img_part.add_header("Content-ID", "<complaint_photo>")
                img_part.add_header("Content-Disposition", "inline", filename="complaint_photo")
                msg.attach(img_part)
                embedded = True
                print("[SMTP] Inline image embedded from URL")
            except Exception as e:
                print(f"[SMTP] Inline image fetch failed, will fall back to remote URL: {e}")

        # Attach the HTML (if embedding failed, HTML can still use remote <img src="image_url">)
        alt.attach(MIMEText(html_body or "", "html", "utf-8"))

        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(EMAIL_SENDER, [to_email], msg.as_string())

        print(f"[SMTP] Email sent to {to_email} (inline={'yes' if embedded else 'no'})")
        return {"ok": True}
    except Exception as e:
        print(f"[ERR] SMTP email error: {e}")
        return {"error": str(e)}

    
def send_onesignal_email(to_email: str, subject: str, html_body: str, include_unsubscribed: bool = False):
    """Send email via OneSignal Email channel"""
    if not (ONESIGNAL_APP_ID and ONE_SIGNAL_API_KEY):
        print("[ERR] Missing ONESIGNAL_APP_ID or ONE_SIGNAL_API_KEY in env.")
        return {"error": "missing_credentials"}

    url = "https://api.onesignal.com/notifications"
    payload = {
        "app_id": ONESIGNAL_APP_ID,
        "email_to": [to_email],
        "email_subject": subject,
        "email_body": html_body,
        "include_unsubscribed": include_unsubscribed,
    }
    headers = {
        "Authorization": f"Key {ONE_SIGNAL_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        print("[OneSignal EMAIL] status:", resp.status_code, "response:", data)
        return data
    except Exception as e:
        print("[ERR] OneSignal email error:", e)
        return {"error": str(e)}

class ActionSubmitComplaintResolved(Action):
    """Submit complaint as RESOLVED (status=2) - no employee assignment needed"""
    
    def name(self):
        return "action_submit_complaint_resolved"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict):

        # Get slots
        complaint_title = tracker.get_slot("complaint_title")
        complaint_description = tracker.get_slot("complaint_description")
        complaint_pictures = tracker.get_slot("uploaded_image_url")
        complaint_type = tracker.get_slot("complaint_type")
        complaint_solution = tracker.get_slot("complaint_solution")

        # Get metadata
        metadata = tracker.latest_message.get("metadata", {})
        user_id = int(metadata.get("userId")) if metadata.get("userId") is not None else None
        user_email = metadata.get("email")
        building_id = metadata.get("building_id")

        print("\n" + "="*60)
        print("SUBMITTING COMPLAINT AS RESOLVED")
        print("="*60)
        print(f"User ID: {user_id}")
        print(f"Building ID: {building_id}")
        print(f"Status: 2 (Resolved)")
        print(f"Assigned to: NULL (self-resolved)")
        print("="*60 + "\n")

        if not complaint_title or not complaint_description:
            dispatcher.utter_message("Please provide complete complaint details.")
            return []

        if not complaint_pictures:
            complaint_pictures = "[]"

        sentiment_score = get_sentiment_score(complaint_description)
        rephrased = get_rephrased_description(tracker)
        try:
            # Handle image upload
            if complaint_pictures and isinstance(complaint_pictures, str) and complaint_pictures.startswith("data:image/"):
                try:
                    bucket = os.getenv("B2_BUCKET", "rasabot")
                    public_url, presigned_url, key = upload_to_b2(complaint_pictures, bucket)
                    complaint_pictures = json.dumps([public_url])
                except Exception as e:
                    print(f"Image upload error: {e}")
                    dispatcher.utter_message(f"⚠️ Image upload failed: {e}")
                    complaint_pictures = "[]"
            elif complaint_pictures and complaint_pictures.startswith("["):
                pass
            else:
                complaint_pictures = "[]"

            engine = get_db_engine()

            # INSERT COMPLAINT AS RESOLVED (status = 2)
            query = """
            INSERT INTO complains (building_id, compl_userid, compl_type, compl_title,
            compl_description, compl_date, compl_job_status, compl_solution,
            compl_pictures, created_at, updated_at, sentiment_score)
            VALUES (:building_id, :user_id, :compl_type, :compl_title, :compl_description, CURDATE(), 2,
                    NULL, :compl_pictures, NOW(), NOW(), :sentiment_score)
            """

            with engine.connect() as conn:
                result = conn.execute(
                    text(query),
                    {
                        "compl_type": complaint_type,
                        "compl_title": complaint_title,
                        "compl_description": rephrased,
                        "compl_pictures": complaint_pictures,
                        "compl_solution": complaint_solution,
                        "user_id": user_id,
                        "building_id": building_id,
                        "sentiment_score": sentiment_score,
                    }
                )
                conn.commit()
                complaint_id = result.lastrowid

            print(f"✓ Complaint {complaint_id} inserted as RESOLVED (status=2)")

            # Success message
            dispatcher.utter_message(
                f"✅ Complaint #{complaint_id} submitted and marked as resolved!\n"
                f"The suggested solution has been recorded."
            )

        except Exception as e:
            print(f"\n=== ERROR ===")
            print(f"Error: {str(e)}")
            import traceback
            traceback.print_exc()
            print("=============\n")
            dispatcher.utter_message(f"❌ Error saving complaint: {e}")
            return []

        return [SlotSet("complaint_description_rephrased", rephrased)]



class ActionSubmitComplaintPending(Action):
    """Submit complaint as PENDING (status=0) - with employee assignment"""
    
    def name(self):
        return "action_submit_complaint_pending"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict):

        # Get slots
        complaint_title = tracker.get_slot( "complaint_title")
        complaint_description = tracker.get_slot("complaint_description")
        complaint_pictures = tracker.get_slot("uploaded_image_url")
        complaint_type = tracker.get_slot("complaint_type")
        complaint_solution = tracker.get_slot("complaint_solution")
        
        assigned_employee_id = tracker.get_slot("assigned_employee_id")
        selected_employee_name = tracker.get_slot("selected_employee_name")
        assigned_employee_email = tracker.get_slot("assigned_employee_email")

        # Get metadata
        metadata = tracker.latest_message.get("metadata", {})
        user_id = int(metadata.get("userId")) if metadata.get("userId") is not None else None
        user_email = metadata.get("email")
        building_id = metadata.get("building_id")

        print("\n" + "="*60)
        print("SUBMITTING COMPLAINT AS PENDING")
        print("="*60)
        print(f"User ID: {user_id}")
        print(f"Building ID: {building_id}")
        print(f"Status: 0 (Pending)")
        print(f"ASsigned employee email: {assigned_employee_email}")
        print(f"Assigned to: {selected_employee_name} (ID: {assigned_employee_id})")
        print("="*60 + "\n")
        print(f"image{complaint_pictures}")
        if not complaint_title or not complaint_description:
            dispatcher.utter_message("Please provide complete complaint details.")
            return []

        if not complaint_pictures:
            complaint_pictures = "[]"
        rephrased = get_rephrased_description(tracker)
        sentiment_score = get_sentiment_score(complaint_description)
        
        try:
            # Handle image upload
            if complaint_pictures and isinstance(complaint_pictures, str) and complaint_pictures.startswith("data:image/"):
                try:
                    bucket = os.getenv("B2_BUCKET", "rasabot")
                    public_url, presigned_url, key = upload_to_b2(complaint_pictures, bucket)
                    complaint_pictures = json.dumps([public_url])
                except Exception as e:
                    print(f"Image upload error: {e}")
                    dispatcher.utter_message(f"⚠️ Image upload failed: {e}")
                    complaint_pictures = "[]"
            elif complaint_pictures and complaint_pictures.startswith("["):
                pass
            else:
                complaint_pictures = "[]"

            # Cast employee ID
            try:
                assigned_employee_id = int(float(assigned_employee_id)) if assigned_employee_id is not None else 3
            except Exception:
                assigned_employee_id = 3

            engine = get_db_engine()

            # INSERT COMPLAINT AS PENDING (status = 0)
            query = """
            INSERT INTO complains (building_id, compl_userid, compl_type, compl_title,
            compl_description, compl_date, compl_job_status,
            compl_assigned_to, compl_solution,
            compl_pictures, created_at, updated_at, sentiment_score)
            VALUES (:building_id, :user_id, :compl_type, :compl_title, :compl_description, CURDATE(), 0,
                    :assigned_to, :compl_solution, :compl_pictures, NOW(), NOW(), :sentiment_score)
            """

            with engine.connect() as conn:
                result = conn.execute(
                    text(query),
                    {
                        "compl_type": complaint_type,
                        "compl_title": complaint_title,
                        "compl_description": rephrased,
                        "compl_pictures": complaint_pictures,
                        "compl_solution": complaint_solution,
                        "user_id": user_id,
                        "building_id": building_id,
                        "sentiment_score": sentiment_score,
                        "assigned_to": assigned_employee_id,
                    }
                )
                conn.commit()
                complaint_id = result.lastrowid

            print(f"✓ Complaint {complaint_id} inserted as PENDING (status=0)")

            # CREATE NOTIFICATIONS (same as before)
            with engine.connect() as conn:
                
                # Get assigned employee info
                employee_query = text("""
                    SELECT user_id, user_name, email, user_type
                    FROM users
                    WHERE user_id = :emp_id
                """)
                employee = conn.execute(employee_query, {"emp_id": assigned_employee_id}).fetchone()
                
                # Get tenant/complainer info
                tenant_query = text("""
                    SELECT user_id, user_name, email, user_type
                    FROM users
                    WHERE user_id = :user_id
                """)
                tenant = conn.execute(tenant_query, {"user_id": user_id}).fetchone()
                
                # Check for active contract
                contract_query = text("""
                    SELECT contrat_id, unit_id, tenant_id
                    FROM contrats
                    WHERE tenant_id = :tenant_id AND contrat_status = 1
                    LIMIT 1
                """)
                contract = conn.execute(contract_query, {"tenant_id": user_id}).fetchone()
                
                unit = None
                owner = None
                
                if contract:
                    # Get unit info
                    unit_query = text("""
                        SELECT unit_id, unit_name, user_id
                        FROM unites
                        WHERE unit_id = :unit_id
                    """)
                    unit = conn.execute(unit_query, {"unit_id": contract.unit_id}).fetchone()
                    
                    if unit:
                        # Get owner info
                        owner_query = text("""
                            SELECT user_id, user_name, email
                            FROM users
                            WHERE user_id = :owner_id
                        """)
                        owner = conn.execute(owner_query, {"owner_id": unit.user_id}).fetchone()
                
                # INSERT NOTIFICATIONS
                notifications_to_insert = []
                
                # Notification to assigned employee
                if employee:
                    if contract and tenant and tenant.user_type == 'T':
                        notification_type = "App\\Notifications\\ComplaintAssigned"
                        notification_title = "New Complaint Assigned"
                        notification_body = f"A new complaint \"{complaint_title}\" has been assigned to you from {tenant.user_name} in unit {unit.unit_name if unit else 'N/A'}."
                    else:
                        notification_type = "App\\Notifications\\GeneralComplaintAssigned"
                        notification_title = "New Complaint Assigned"
                        notification_body = f"A new complaint \"{complaint_title}\" has been assigned to you."
                    
                    notification_data = {
                        "title": notification_title,
                        "body": notification_body,
                        "type": "Complaint"
                    }
                    
                    notifications_to_insert.append({
                        "id": str(uuid.uuid4()),
                        "type": notification_type,
                        "notifiable_type": "App\\Models\\User",
                        "notifiable_id": employee.user_id,
                        "data": json.dumps(notification_data),
                        "read_at": None,
                        "created_at": datetime.now(),
                        "updated_at": datetime.now()
                    })
                    
                    print(f"✓ Notification created for employee: {employee.user_name}")
                
                # Notification to owner (if tenant complaint)
                if owner and tenant and contract and unit:
                    notification_title = "New Complaint From Tenant"
                    notification_body = f"Your tenant {tenant.user_name} in unit {unit.unit_name} has submitted a complaint: \"{complaint_title}\"."
                    
                    notification_data = {
                        "title": notification_title,
                        "body": notification_body,
                        "type": "Complaint"
                    }
                    
                    notifications_to_insert.append({
                        "id": str(uuid.uuid4()),
                        "type": "App\\Notifications\\ComplaintFromTenant",
                        "notifiable_type": "App\\Models\\User",
                        "notifiable_id": owner.user_id,
                        "data": json.dumps(notification_data),
                        "read_at": None,
                        "created_at": datetime.now(),
                        "updated_at": datetime.now()
                    })
                    
                    print(f"✓ Notification created for owner: {owner.user_name}")
                
                # Insert all notifications
                if notifications_to_insert:
                    insert_notification_query = text("""
                        INSERT INTO notifications (id, type, notifiable_type, notifiable_id, data, read_at, created_at, updated_at)
                        VALUES (:id, :type, :notifiable_type, :notifiable_id, :data, :read_at, :created_at, :updated_at)
                    """)
                    
                    for notif in notifications_to_insert:
                        conn.execute(insert_notification_query, notif)
                    
                    conn.commit()
                    print(f"✓ Inserted {len(notifications_to_insert)} notifications into database")

            # SEND EMAIL (same as before)
            try:
                if assigned_employee_email:
                    first_pic_url = None
                    if complaint_pictures and complaint_pictures.startswith("["):
                        try:
                            pics = json.loads(complaint_pictures)
                            if pics:
                                first_pic_url = pics[0]
                        except Exception:
                            pass

                    badge_colors = {
                        "Electricity failure": "#F59E0B",
                        "Plumbing failure": "#3B82F6",
                        "Technical failure": "#10B981",
                        "Caretaker failure": "#EF4444",
                    }
                    badge_color = badge_colors.get(complaint_type, "#6B7280")

                    subject = f"New Complaint #{complaint_id} • {complaint_type or 'Complaint'}"

                    img_section = ""
                    if first_pic_url:
                        img_section = f"""
                        <tr>
                        <td style="padding-top:16px;">
                            <div style="font-size:14px;color:#374151;margin-bottom:8px;">Photo</div>
                            <img src="cid:complaint_photo" alt="Complaint photo" style="max-width:100%;border-radius:12px;border:1px solid #e5e7eb;">
                            <div style="margin-top:8px;font-size:13px;">
                            <a href="{first_pic_url}" target="_blank" style="color:#2563EB;text-decoration:none;">Open image in browser</a>
                            </div>
                        </td>
                        </tr>
                        """

                    body = f"""
                    <div style="background:#f8fafc;padding:24px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:16px;border:1px solid #e5e7eb;box-shadow:0 1px 2px rgba(0,0,0,.04);">
                        <tr>
                        <td style="padding:24px 24px 8px 24px;">
                            <div style="font-size:18px;font-weight:700;color:#111827;">New Complaint Assigned</div>
                            <div style="margin-top:6px;font-size:13px;color:#6B7280;">Complaint #{complaint_id} • Building {building_id}</div>
                            <span style="display:inline-block;margin-top:12px;padding:6px 10px;border-radius:999px;background:{badge_color};color:white;font-size:12px;font-weight:600;">
                            {complaint_type or 'Complaint'}
                            </span>
                        </td>
                        </tr>
                        <tr>
                        <td style="padding:8px 24px 24px 24px;">
                            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:separate;border-spacing:0 8px;">
                            <tr>
                                <td style="width:140px;font-size:13px;color:#6B7280;">Title</td>
                                <td style="font-size:14px;color:#111827;font-weight:600;">{(complaint_title or '').strip()}</td>
                            </tr>
                            <tr>
                                <td style="width:140px;font-size:13px;color:#6B7280;">Type</td>
                                <td style="font-size:14px;color:#111827;">{complaint_type or '-'}</td>
                            </tr>
                            <tr>
                                <td style="width:140px;font-size:13px;color:#6B7280;vertical-align:top;">Description</td>
                                <td style="font-size:14px;color:#111827;line-height:1.5;">{(complaint_description or '').strip()}</td>
                            </tr>
                            </table>
                            {img_section}
                            <div style="margin-top:20px;">
                            <a href="#" style="display:inline-block;background:#111827;color:#ffffff;text-decoration:none;padding:10px 14px;border-radius:10px;font-size:13px;font-weight:600;">Open in Dashboard</a>
                            </div>
                        </td>
                        </tr>
                    </table>
                    <div style="max-width:680px;margin:10px auto 0;text-align:center;color:#9CA3AF;font-size:12px;">
                        Sent by Building Bot
                    </div>
                    </div>
                    """

                    text_fallback = f"""New Complaint Assigned
                Complaint #{complaint_id} - Building {building_id}
                Type: {complaint_type or '-'}
                Title: {(complaint_title or '').strip()}
                Description: {(rephrased or '').strip()}
                {('Photo: ' + first_pic_url) if first_pic_url else ''}"""

                    employee_email_from_db = employee.email if employee and getattr(employee, "email", None) else None
                    email_to_send = assigned_employee_email or employee_email_from_db

                    if not email_to_send:
                        raise ActionExecutionRejected(self.name(), "Assigned employee email is missing.")

                    if EMAIL_PROVIDER == "smtp":
                        resp = send_smtp_email(email_to_send, subject, body, text_fallback=text_fallback, image_url=first_pic_url)
                    else:
                        resp = send_onesignal_email(email_to_send, subject, body, include_unsubscribed=False)

                    if not resp or not resp.get("ok", False):
                        if EMAIL_PROVIDER != "smtp" and isinstance(resp, dict) and "id" in resp:
                            pass
                        else:
                            err_msg = f"Email send failed via {EMAIL_PROVIDER}: {resp}"
                            raise ActionExecutionRejected(self.name(), err_msg)

                    print(f"✓ Email sent to {email_to_send} via {EMAIL_PROVIDER.upper()}")

            except Exception as notify_err:
                print(f"✗ Email notification error: {notify_err}")

            # Success message
            employee_msg = f" and assigned to {selected_employee_name}" if selected_employee_name else ""
            dispatcher.utter_message(
                f"✅ Complaint #{complaint_id} submitted successfully{employee_msg}!\n"
                f"📧 Notifications sent"
            )

        except Exception as e:
            print(f"\n=== ERROR ===")
            print(f"Error: {str(e)}")
            import traceback
            traceback.print_exc()
            print("=============\n")
            dispatcher.utter_message(f"❌ Error saving complaint: {e}")
            return []

        return [SlotSet("complaint_description_rephrased", rephrased)]

    
from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
from sqlalchemy import create_engine, text

class ActionCheckComplaintStatus(Action):
    def name(self):
        return "action_check_complaint_status"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: dict):
        
        # Get user info from metadata
        metadata = tracker.latest_message.get("metadata", {})
        user_id = metadata.get("userId")
        
        # Get complaint ID from slot
        complaint_id = tracker.get_slot("complaint_id")
        
        print("=== CHECK COMPLAINT STATUS ===")
        print(f"User ID: {user_id}")
        print(f"Complaint ID: {complaint_id}")
        print("==============================")
        
        if not user_id:
            dispatcher.utter_message("❌ Unable to identify user.")
            return []
        
        if not complaint_id:
            dispatcher.utter_message(
                "Please provide the complaint ID.\nExample: 'check complaint 123'"
            )
            return []

        try:
            engine = get_db_engine()

            query = text("""
                SELECT compl_id, compl_title, compl_type, compl_date,
                       compl_job_status, compl_description, compl_solution
                FROM complains
                WHERE compl_id = :complaint_id 
                AND compl_userid = :user_id
            """)

            with engine.connect() as conn:
                result = conn.execute(query, {
                    "complaint_id": complaint_id,
                    "user_id": user_id
                }).fetchone()

            if not result:
                dispatcher.utter_message(
                    f"❌ Complaint #{complaint_id} not found or doesn't belong to you."
                )
            else:
                status_map = {
                    0: "🕒 Pending",
                    1: "🔧 In Progress",
                    2: "✅ Resolved"
                }
                
                type_emoji = {
                    "Electricity failure": "⚡",
                    "Plumbing failure": "💧",
                    "Technical failure": "🔧",
                    "Caretaker failure": "🧹"
                }
                
                status = status_map.get(result.compl_job_status, "❓ Unknown")
                emoji = type_emoji.get(result.compl_type, "📝")
                
                message = f"📋 **Complaint #{result.compl_id}**\n\n"
                message += f"{emoji} **{result.compl_title}**\n\n"
                message += f"**Status:** {status}\n"
                message += f"**Type:** {result.compl_type}\n"
                message += f"**Date:** {result.compl_date}\n"
                message += f"**Description:** {result.compl_description}\n"
                
                if result.compl_solution:
                    message += f"\n**Solution:** {result.compl_solution}\n"

                dispatcher.utter_message(text=message)

        except Exception as e:
            print(f"ERROR: {e}")
            dispatcher.utter_message(f"⚠️ Error: {str(e)}")

        return [SlotSet("complaint_id", None)]  # Reset slot after use
    
class ActionFetchEmployeesAndWait(Action):
    def name(self) -> Text:
        return "action_fetch_employees_and_wait"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        print("\n" + "="*50)
        print("FETCHING EMPLOYEES")
        print("="*50)

        complaint_type = tracker.get_slot("complaint_type")
        if not complaint_type:
            return []

        role_mapping = {
            "Electricity failure": "Electrician",
            "Plumbing failure": "Plumber",
            "Technical failure": "Technician",
            "Caretaker failure": "Caretaker"
        }

        required_role = role_mapping.get(complaint_type)
        print(f"Required role: {required_role}")

        if not required_role:
            dispatcher.utter_message(text="⚠️ Unable to determine required employee type.")
            return [
                SlotSet("assigned_employee_id", "3"),
                SlotSet("selected_employee_name", "Default Staff"),
                SlotSet("employees_shown", False)
            ]

        try:
            engine = get_db_engine()
            query = text("""
                SELECT user_id, user_name, email
                FROM users
                WHERE specialty = :role
                ORDER BY user_name
                LIMIT 5
            """)
            with engine.connect() as conn:
                results = conn.execute(query, {"role": required_role}).fetchall()

            print(f"Found {len(results)} employees")

            if not results:
                dispatcher.utter_message(
                    text=f"⚠️ No available {required_role}s found."
                )
                return [
                    SlotSet("assigned_employee_id", "3"),
                    SlotSet("selected_employee_name", "Default Staff"),
                    SlotSet("employees_shown", False),
                    SlotSet("assigned_employee_email", None)
                ]

            employees = []
            buttons = []

            for emp in results:
                employees.append({
                    "user_id": emp.user_id,
                    "user_name": emp.user_name,
                    "email": emp.email
                })
                
                payload_data = {
                    "assigned_employee_id": str(emp.user_id),
                    "selected_employee_name": emp.user_name,
                    "assigned_employee_email": emp.email or ""
                }
                buttons.append({
                    "title": emp.user_name,
                    "payload": f'/set_employee{json.dumps(payload_data)}'
                })
                print(f"Button created: {emp.user_name} -> {payload_data}")

            dispatcher.utter_message(
                text=f"👷 Available {required_role}s - Please select one:",
                buttons=buttons
            )

            return [
                SlotSet("available_employees", json.dumps(employees)),
                SlotSet("required_role", required_role),
                SlotSet("employees_shown", True)
            ]

        except Exception as e:
            print(f"[Employee Fetch Error] {e}")
            import traceback
            traceback.print_exc()
            dispatcher.utter_message(text=f"⚠️ Error fetching employees")
            return [
                SlotSet("assigned_employee_id", "3"),
                SlotSet("selected_employee_name", "Default Staff"),
                SlotSet("employees_shown", False)
            ]

class ActionDefaultFallback(Action):
    """Custom fallback - silent when selecting employee"""
    
    def name(self) -> Text:
        return "action_default_fallback"
    
    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        print("\n[FALLBACK] Triggered")
        
        user_message = tracker.latest_message.get("text", "").strip()
        
        # Ignore SetSlots commands
        if user_message.startswith("/SetSlots") or user_message.startswith("/set_employee"):
            print("[FALLBACK] Ignoring command")
            return []
        
        # Check if waiting for employee selection
        employees_shown = tracker.get_slot("employees_shown")
        
        if employees_shown:
            print("[FALLBACK] Silently ignoring during employee selection")
            return []
        
        # Normal fallback
        print("[FALLBACK] Normal fallback")
        dispatcher.utter_message(
            text="I'm sorry, I didn't understand that. Could you rephrase?"
        )
        return []


class ActionSelectEmployee(Action):
    def name(self) -> Text:
        return "action_select_employee"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        selected_name = tracker.get_slot("selected_employee_name")
        assigned_id = tracker.get_slot("assigned_employee_id")
        available_employees_json = tracker.get_slot("available_employees")

        if assigned_id and selected_name:
            dispatcher.utter_message(text=f"✅ Assigned to {selected_name}")
            return []

        if selected_name and available_employees_json and available_employees_json != "[]":
            try:
                available = json.loads(available_employees_json)
                for emp in available:
                    if emp["user_name"].lower() == selected_name.lower():
                        dispatcher.utter_message(text=f"✅ Assigned to {emp['user_name']}")
                        return [
                            SlotSet("assigned_employee_id", str(emp["user_id"])),
                            SlotSet("assigned_employee_email", emp.get("email")),  # <-- set it
                        ]
            except Exception as e:
                print(f"[SelectEmployee error] {e}")

        dispatcher.utter_message(text="No valid selection. Assigning to default staff.")
        return [
            SlotSet("assigned_employee_id", "3"),
            SlotSet("selected_employee_name", "Default Staff")
        ]


class ActionSummarizeComplaint(Action):
    def name(self) -> Text:
        return "action_summarize_complaint"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        title = tracker.get_slot("complaint_title")
        desc = tracker.get_slot("complaint_description")
        ctype = tracker.get_slot("complaint_type")
        image = tracker.get_slot("uploaded_image_url")
        rephrased = get_rephrased_description(tracker)
        summary = "Here is what I understood about your complaint:\n\n"
        summary += f"📝 Title: {title or '-'}\n"
        summary += f"📖 Description: {rephrased or '-'}\n"
        summary += f"⚡ Type: {ctype or '-'}\n"
        summary += f"📷 Photo: {'attached' if image else 'no photo'}\n"

        dispatcher.utter_message(text=summary)
        return [SlotSet("complaint_description_rephrased", rephrased)]



class ActionProposeComplaintSolution(Action):
    """
    OPTIMIZED: Faster RAG search with lazy loading
    """
    
    # Class-level cache for KB (initialize once, reuse)
    _kb_instance = None
    
    @classmethod
    def get_kb(cls):
        """Lazy load and cache KB instance"""
        if cls._kb_instance is None:
            try:
                import sys
                import os
                from pathlib import Path
                
                project_root = Path(__file__).parent.parent
                if str(project_root) not in sys.path:
                    sys.path.insert(0, str(project_root))
                
                from rag.knowledge_base import ComplaintKnowledgeBase
                cls._kb_instance = ComplaintKnowledgeBase(persist_directory="./chroma_db")
                print("✅ KB initialized and cached")
            except Exception as e:
                print(f"⚠️ KB init failed: {e}")
                cls._kb_instance = None
        return cls._kb_instance
    
    def name(self) -> Text:
        return "action_propose_complaint_solution"
    
    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        import time
        start_time = time.time()
        
        # Get complaint details
        title = tracker.get_slot("complaint_title") or "Unknown"
        desc = tracker.get_slot("complaint_description") or "Unknown"
        ctype = tracker.get_slot("complaint_type") or "Unknown"
        
        # Get image (simplified)
        existing_img = tracker.get_slot("uploaded_image_url")
        img = None
        try:
            events = tracker.events or []
            for event in reversed(events[-10:]):
                if event.get("event") == "user":
                    md = event.get("metadata") or {}
                    if md.get("uploaded_image_url"):
                        img = md["uploaded_image_url"]
                        dispatcher.utter_message(text="📷 Image received!")
                        break
        except Exception as e:
            print(f"[Image] Error: {e}")
        
        img_for_prompt = img or existing_img
        img_text = "no image" if not img_for_prompt else "image attached"

        print(f"\n⏱️ Starting solution generation...")
        
        # ⭐ STEP 1: RAG SEARCH (with timeout protection)
        similar_complaints = []
        context = ""
        
        try:
            kb = self.get_kb()  # Use cached instance!
            
            if kb:
                search_start = time.time()
                
                print(f"⚠️ RAG error: {ctype}")

                # Search with timeout protection
                search_query = f"{title}. {desc}"
                type_for_search = ctype if ctype not in (None, "", "Unknown") else None

                similar_complaints = kb.search_similar_complaints(
                    query=search_query,
                    complaint_type=type_for_search,
                    top_k=3
                )
                
                search_time = time.time() - search_start
                print(f"🔍 RAG search took {search_time:.2f}s")
                
                # Build context
                if similar_complaints:
                    context = "Similar cases:\n"
                    for i, comp in enumerate(similar_complaints[:2], 1):  # Limit to 2 for speed
                        similarity = comp['similarity_score'] * 100
                        context += f"{i}. [{similarity:.0f}%] {comp['title']}: {comp['solution'][:80]}\n"
                    print(f"✅ Found {len(similar_complaints)} similar cases")
                else:
                    print("⚠️ No similar cases found")
            else:
                print("⚠️ KB not available")
                
        except Exception as rag_error:
            print(f"⚠️ RAG error: {rag_error}")
            context = ""
        
        # ⭐ STEP 2: GENERATE SOLUTION (optimized prompt)
        
        # Shorter, faster prompt
        if similar_complaints:
            prompt = f"""Complaint: {desc}
Type: {ctype}

Past solutions in this building:
{context}

Give a concise solution (max 150 chars) based on what worked before."""
        else:
            prompt = f"""Complaint: {desc}
Type: {ctype}

Give a concise troubleshooting solution (max 150 chars)."""

        try:
            gpt_start = time.time()
            
            completion = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=100,  # Reduced for speed
                timeout=10  # Add timeout
            )
            
            solution = completion.choices[0].message.content.strip()
            
            gpt_time = time.time() - gpt_start
            print(f"🤖 GPT took {gpt_time:.2f}s")
            
            # Add badge if RAG was used
            if similar_complaints:
                solution = f"💡 Based on {len(similar_complaints)} similar case(s): {solution}"
            
        except Exception as e:
            print(f"❌ GPT error: {e}")
            solution = "Unable to generate solution. Please contact maintenance."
        
        total_time = time.time() - start_time
        print(f"⏱️ TOTAL TIME: {total_time:.2f}s\n")
        
        # Return
        slot_updates = [SlotSet("complaint_solution", solution)]
        if img is not None:
            slot_updates.append(SlotSet("uploaded_image_url", img))
        
        return slot_updates

class ActionExtractImageFromMetadata(Action):
    def name(self):
        return "action_extract_image_from_metadata"

    def run(self, dispatcher, tracker, domain: Dict[Text, Any]) -> List[SlotSet]:
        events = tracker.events
        img_b64 = None

        for event in reversed(events[-10:]):
            if event.get("event") == "user":
                md = event.get("metadata") or {}
                if md.get("uploaded_image_url"):
                    img_b64 = md.get("uploaded_image_url")
                    break

        if not img_b64:
            dispatcher.utter_message(text="⏭️ No image detected, continuing without photo...")
            return [
                SlotSet("uploaded_image_url", None),
                SlotSet("image_uploaded", False),
                SlotSet("image_analysis", None),
            ]

        dispatcher.utter_message(text="📷 Image received! Analyzing...")

        analysis = None
        try:
            analysis = analyze_complaint_image(img_b64)
        except Exception as e:
            print(f"[Image analysis error] {e}")

        if analysis:
            dispatcher.utter_message(text=f"🧾 Image notes:\n{analysis}")

        return [
            SlotSet("uploaded_image_url", img_b64),
            SlotSet("image_uploaded", True),
            SlotSet("image_analysis", analysis),
        ]



class ActionInferComplaintType(Action):
    def name(self) -> Text:
        return "action_infer_complaint_type"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        latest_text = tracker.latest_message.get("text", "")
        if not latest_text:
            return []

        categories = [
            "Electricity failure",
            "Plumbing failure",
            "Technical failure",
            "Caretaker failure"
        ]

        prompt = f"""
        Classify the following complaint into exactly one of these categories:
        {", ".join(categories)}.

        Category descriptions:
        - "Electricity failure": Power outages, lights, electrical outlets, circuit breakers
        - "Plumbing failure": Water leaks, drains, toilets, sinks, pipes, faucets
        - "Technical failure": Heating, AC, elevators, door locks, appliances, ventilation
        - "Caretaker failure": Cleaning, trash collection, maintenance service, common areas

        Complaint: "{latest_text}"

        Answer with ONLY the exact category name from the list above.
        """

        try:
            response = openai.Completion.create(
                model="gpt-3.5-turbo-instruct",
                prompt=prompt,
                max_tokens=10,
                temperature=0
            )
            complaint_type = response.choices[0].text.strip()
        except Exception as e:
            print(f"[GPT ERROR] {e}")
            return []

        if complaint_type in categories:
            return [SlotSet("complaint_type", complaint_type)]
        return []


class ActionValidateComplaintType(Action):
    def name(self) -> Text:
        return "action_validate_complaint_type"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        ctype = (tracker.get_slot("complaint_type") or "").strip()

        allowed_types = {
            "Electricity failure",
            "Plumbing failure",
            "Technical failure",
            "Caretaker failure"
        }

        if ctype not in allowed_types:
            dispatcher.utter_message(
                text="Please choose one of the categories: Electricity failure, Plumbing failure, Technical failure, or Caretaker failure."
            )
            return [SlotSet("complaint_type", None)]

        return [SlotSet("complaint_type", ctype)]


from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from sqlalchemy import create_engine, text

class ActionListUserComplaints(Action):
    def name(self) -> Text:
        return "action_list_user_complaints"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: dict) -> List[Dict[Text, Any]]:

        # --- who is asking ---
        metadata = tracker.latest_message.get("metadata", {}) or {}
        user_id = metadata.get("userId")
        if not user_id:
            dispatcher.utter_message(text="❌ Unable to identify user. Please try again.")
            return []

        # --- parse requested count & direction ---
        # slot provided via NLU entity [5](complaint_count)
        raw_count = tracker.get_slot("complaint_count")
        try:
            limit = int(raw_count) if raw_count is not None else 5  # default to 5
        except Exception:
            limit = 5
        limit = max(1, min(limit, 50))  # clamp 1..50

        # direction: detect words in the user text
        user_text = (tracker.latest_message.get("text") or "").lower()
        wants_oldest = any(k in user_text for k in ["oldest", "first"])
        # if they explicitly said "latest / most recent / last", keep default DESC
        order_dir = "ASC" if wants_oldest else "DESC"  # WHITELISTED

        # --- build query ---
        # Prefer an exact timestamp field if you have it.
        # This orders by updated_at/created_at when present, else compl_date, then compl_id.
        order_sql = "COALESCE(updated_at, created_at, compl_date) " + order_dir + ", compl_id " + order_dir

        sql = text(f"""
            SELECT compl_id, compl_title, compl_type, compl_date, compl_job_status
            FROM complains
            WHERE compl_userid = :user_id
            ORDER BY {order_sql}
            LIMIT :limit
        """)

        try:
            engine = get_db_engine()
            with engine.connect() as conn:
                rows = conn.execute(sql, {"user_id": user_id, "limit": int(limit)}).fetchall()

            if not rows:
                dispatcher.utter_message(text="📋 You haven't submitted any complaints yet.")
                return []

            status_map = {0: "🕒 Pending", 1: "🔧 In Progress", 2: "✅ Resolved"}
            type_emoji = {
                "Electricity failure": "⚡",
                "Plumbing failure": "💧",
                "Technical failure": "🔧",
                "Caretaker failure": "🧹",
            }

            heading = "📋 Oldest complaints:\n\n" if wants_oldest else "📋 Latest complaints:\n\n"
            msg = [heading]
            for r in rows:
                status = status_map.get(r.compl_job_status, "❓ Unknown")
                emoji = type_emoji.get(r.compl_type, "📝")
                msg.append(f"{emoji} **#{r.compl_id}** - {r.compl_title}\n   Status: {status}\n   Date: {r.compl_date}\n")

            msg.append("\n💡 Tip: say “last 3 complaints” or “oldest 3 complaints”.")
            dispatcher.utter_message(text="".join(m + ("\n" if not m.endswith("\n") else "") for m in msg))
            return []

        except Exception as e:
            dispatcher.utter_message(text=f"⚠️ Error retrieving complaints: {str(e)}")
            return []

def analyze_complaint_image(img_data_url: str) -> str:
    """
    Returns a short, complaint-relevant analysis.
    img_data_url is a data:image/...;base64,... string.
    """
    prompt = (
        "You are analyzing an uploaded photo for a building maintenance complaint.\n"
        "Describe ONLY what is visible and relevant to maintenance.\n"
        "Do NOT guess hidden causes.\n"
        "Output 2-4 bullet points max."
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": img_data_url}},
                ],
            }
        ],
    )
    return (resp.choices[0].message.content or "").strip()
def get_rephrased_description(tracker: Tracker) -> str:
    """
    Returns complaint_description_rephrased if already set,
    otherwise generates it once and returns it.
    """
    cached = tracker.get_slot("complaint_description_rephrased")
    if cached:
        return cached

    raw = (tracker.get_slot("complaint_description") or "").strip()
    if not raw:
        return ""

    prompt = (
        "Rephrase the complaint into a concise, neutral, professional description.\n"
        "Rules:\n"
        "- 1–2 sentences\n"
        "- max 400 characters\n"
        "- remove emotions and personal details\n"
        "- use different words than the original\n\n"
        f"User text: {raw}\n\n"
        'Return only JSON: {"description":"..."}'
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )

        txt = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{.*\}", txt, re.DOTALL)

        if m:
            data = json.loads(m.group(0))
            clean = (data.get("description") or "").strip()
        else:
            clean = txt.strip()

        return clean[:400]

    except Exception as e:
        print("[Rephrase error]", e)
        return raw[:400]
class ActionValidateImageMatchesDescription(Action):
    def name(self) -> Text:
        return "action_validate_image_matches_description"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        img_b64 = tracker.get_slot("uploaded_image_url")
        if not img_b64 or not isinstance(img_b64, str) or not img_b64.startswith("data:image/"):
            # no image -> treat as match and continue
            return [SlotSet("image_match", True), SlotSet("image_mismatch_reason", None)]

        # use your rephrased text (better for matching)
        desc = (tracker.get_slot("complaint_description_rephrased") or "").strip()
        if not desc:
            desc = (tracker.get_slot("complaint_description") or "").strip()

        # If still empty, don't block user
        if not desc:
            return [SlotSet("image_match", True), SlotSet("image_mismatch_reason", None)]

        img_notes = tracker.get_slot("image_analysis")
        if not img_notes:
            try:
                img_notes = analyze_complaint_image(img_b64)
            except Exception as e:
                print("[validate_image] analysis failed:", e)
                img_notes = ""

        prompt = f"""
You are checking whether a maintenance complaint PHOTO matches the complaint DESCRIPTION.

DESCRIPTION:
{desc}

IMAGE NOTES (what is visible):
{img_notes}

Decide if they match.
Return ONLY JSON:
{{
  "match": true/false,
  "reason": "short reason (max 140 chars)"
}}
Rules:
- If unsure, set match=true (avoid false alarms)
- Use match=false only when clearly unrelated
"""

        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.2,
                max_tokens=120,
                messages=[{"role": "user", "content": prompt}],
            )
            txt = (resp.choices[0].message.content or "").strip()
            m = re.search(r"\{.*\}", txt, re.DOTALL)
            data = json.loads(m.group(0)) if m else {"match": True, "reason": ""}

            is_match = bool(data.get("match", True))
            reason = (data.get("reason") or "").strip()[:140]

            return [
                SlotSet("image_match", is_match),
                SlotSet("image_mismatch_reason", reason if not is_match else None),
                SlotSet("image_analysis", img_notes or tracker.get_slot("image_analysis")),
            ]

        except Exception as e:
            print("[validate_image] error:", e)
            # fail-open
            return [SlotSet("image_match", True), SlotSet("image_mismatch_reason", None)]

class ActionResetUploadedImage(Action):
    def name(self) -> Text:
        return "action_reset_uploaded_image"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]):
        return [
            SlotSet("uploaded_image_url", None),
            SlotSet("image_uploaded", False),
            SlotSet("image_analysis", None),
            SlotSet("image_match", None),
            SlotSet("image_mismatch_reason", None),
            SlotSet("confirm_use_image", None),
        ]
