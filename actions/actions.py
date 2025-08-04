# This files contains your custom actions which can be used to run
# custom Python code.
#
# See this guide on how to implement these action:
# https://rasa.com/docs/rasa/custom-actions


# This is a simple example for a custom action which utters "Hello World!"

# from typing import Any, Text, Dict, List
#
# from rasa_sdk import Action, Tracker
# from rasa_sdk.executor import CollectingDispatcher
#
#
# class ActionHelloWorld(Action):
#
#     def name(self) -> Text:
#         return "action_hello_world"
#
#     def run(self, dispatcher: CollectingDispatcher,
#             tracker: Tracker,
#             domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
#
#         dispatcher.utter_message(text="Hello World!")
#
#         return []

from typing import Any, Text, Dict, List


from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
import mysql.connector
from datetime import datetime
import base64
import requests

class ActionSaveComplaint(Action):
    def name(self):
        return "action_save_complaint"

    def run(self, dispatcher, tracker, domain):
        #msg = tracker.latest_message.get("text")

        compl_title = tracker.get_slot("compl_title")
        compl_description = tracker.get_slot("compl_description") 
        compl_pictures = tracker.get_slot("compl_pictures") 
        compl_type = self.get_complaint_type(compl_description)  #Analyse automatique du type de réclamation
        if not compl_title or not compl_description:
         dispatcher.utter_message("Please provide complete complaint details.")
         return []
    
        if not compl_pictures:
            compl_pictures = "[]"
        try:
            conn = mysql.connector.connect(host="localhost", database="bms_ged", user="root", password="")
            cursor = conn.cursor()
            query = """
                INSERT INTO complains (building_id, user_id, compl_type, compl_title,
                compl_description, compl_date, compl_job_status,
                compl_assigned_to, compl_solution, compl_complainBy,
                compl_pictures, compl_email, compl_phone, created_at, updated_at)
                VALUES (1,1,%s,%s,%s,CURDATE(),0,
                        'Personne','','Utilisateur',%s,NULL,NULL,NOW(),NOW())
            """
            cursor.execute(query, (compl_type, compl_title, compl_description, compl_pictures))
            conn.commit()
            dispatcher.utter_message("Complaint saved.")

        except Exception as e:
            dispatcher.utter_message(f" Erreur : {e}")
        finally:
            cursor.close()
            conn.close()
        return []

    def get_complaint_type(self, description):
        description = (description or "").lower()
        if "water" in description or "leak" in description:
            return "Plomberie"
        elif "electric" in description or "light" in description:
            return "Électricité"
        elif "door" in description or "security" in description:
            return "Sécurité"
        else:
            return "Autre"


class ActionCheckStatusComplaint(Action):
    def name(self):
        return "action_check_status_complaint"

    def run(self, dispatcher: CollectingDispatcher, tracker, domain):
        complaint_id = tracker.get_slot("complaint_id")

        if not complaint_id:
            dispatcher.utter_message("Please provide the complaint ID.")
            return []

        try:
            
            conn = mysql.connector.connect(
                host="localhost",
                database="bms_ged",
                user="root",
                password=""
            )
            cursor = conn.cursor()

            #get the status
            query = "SELECT compl_job_status FROM complains WHERE compl_id = %s"
            cursor.execute(query, (complaint_id,))
            result = cursor.fetchone()

            if result:
                status_code = result[0]
                status_map = {
                    0: "Pending",
                    1: "In progress",
                    2: "Resolved"
                }
                status_text = status_map.get(status_code, "Unknown")

                dispatcher.utter_message(
                    f"The status of complaint {complaint_id} is: {status_text}."
                )
            else:
                dispatcher.utter_message(
                    f"No complaint found with ID {complaint_id}."
                )

        except Exception as e:
            dispatcher.utter_message(
                f"Error accessing the database: {e}"
            )

        finally:
            cursor.close()
            conn.close()

        return []
    
class ActionHandleImage(Action):
    def name(self) -> str:
        return "action_handle_image"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: dict) -> List[Dict[Text, Any]]:
        
        custom = tracker.latest_message.get("custom", {})
        image_data = custom.get("image_data")
        file_name = custom.get("file_name")

        if image_data:
            dispatcher.utter_message(text=f"Image '{file_name}' received!")
        else:
            dispatcher.utter_message(text="No image received.")

        return []
