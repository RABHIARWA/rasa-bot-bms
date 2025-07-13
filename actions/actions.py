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

class ActionSaveComplaint(Action):
    def name(self):
        return "action_save_complaint"

    def run(self, dispatcher, tracker, domain):
        msg = tracker.latest_message.get("text")
        try:
            conn = mysql.connector.connect(host="localhost", database="bms_ged", user="root", password="")
            cursor = conn.cursor()
            query = """
                INSERT INTO complains (building_id, user_id, compl_type, compl_title,
                compl_description, compl_date, compl_job_status,
                compl_assigned_to, compl_solution, compl_complainBy,
                compl_pictures, compl_email, compl_phone, created_at, updated_at)
                VALUES (1,1,'TypeA','Réclamation',%s,CURDATE(),0,
                        'Personne','','Utilisateur','[]',NULL,NULL,NOW(),NOW())
            """
            cursor.execute(query, (msg,))
            conn.commit()
            dispatcher.utter_message("Réclamation enregistrée.")
        except Exception as e:
            dispatcher.utter_message(f" Erreur : {e}")
        finally:
            cursor.close()
            conn.close()
        return []


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