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
