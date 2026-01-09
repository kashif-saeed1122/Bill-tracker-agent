from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os
import pickle
import base64
from typing import Dict, Optional
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from src.modules.llm_interface import LLMInterface
from src.config.settings import settings

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

class EmailScanner:
    
    def __init__(self, credentials_path: str = 'credentials.json', token_path: str = 'token.json'):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None
        self.download_dir = "data/raw/attachments"
        os.makedirs(self.download_dir, exist_ok=True)
        self.filtered_emails_log = []
    
    def authenticate(self):
        creds = None
        if os.path.exists(self.token_path):
            with open(self.token_path, 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(self.token_path, 'wb') as token:
                pickle.dump(creds, token)
        
        self.service = build('gmail', 'v1', credentials=creds)
        return True
    
    def _is_relevant_via_llm(self, user_query: str, sender: str, subject: str, body: str) -> Dict[str, any]:        
        try:
            email_content = f"From: {sender}\nSubject: {subject}\n\n{body[:1000]}"
            
            llm = LLMInterface(settings.OPENAI_API_KEY, settings.OPENAI_MODEL)
            result = llm.evaluate_relevance(query=user_query, document=email_content)
            
            return {
                "is_relevant": result.get("is_relevant", False),
                "score": result.get("relevance_score", 0.0),
                "reason": result.get("reasoning", "")
            }
        except Exception as e:
            print(f"   ⚠️ LLM relevance check failed: {e}")
            return {"is_relevant": True, "score": 1.0, "reason": "LLM check failed, included by default"}
    
    def _sanitize_filename(self, text: str) -> str:
        safe = re.sub(r'[^a-zA-Z0-9\s]', '', text)
        return re.sub(r'\s+', '_', safe.strip())

    def _download_attachment(self, message_id: str, attachment_id: str, filename: str) -> str:
        try:
            attachment = self.service.users().messages().attachments().get(
                userId='me', messageId=message_id, id=attachment_id
            ).execute()
            
            file_data = base64.urlsafe_b64decode(attachment['data'])
            filepath = os.path.join(self.download_dir, filename)
            
            counter = 1
            base_name = filename
            while os.path.exists(filepath):
                name, ext = os.path.splitext(base_name)
                filepath = os.path.join(self.download_dir, f"{name}_{counter}{ext}")
                counter += 1
            
            with open(filepath, 'wb') as f:
                f.write(file_data)
            return filepath
        except Exception as e:
            print(f"Error downloading {filename}: {e}")
            return None
    
    def _get_message_body(self, payload):
        body = ""
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    if 'data' in part['body']:
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                        break
                elif part['mimeType'] == 'text/html' and not body:
                    if 'data' in part['body']:
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                elif 'parts' in part:
                    body = self._get_message_body(part)
                    if body: break
        elif 'body' in payload and 'data' in payload['body']:
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
        return body
    
    def scan(self, 
             date_from: str, 
             date_to: str, 
             custom_query: Optional[str] = None,
             user_query: Optional[str] = None,
             max_results: int = 50, 
             require_attachments: bool = True, 
             use_filtering: bool = True) -> Dict:
        
        if not self.service:
            self.authenticate()
        
        self.filtered_emails_log = []
        
        # Construct the Gmail query string
        query = f'after:{date_from} before:{date_to}'
        
        if require_attachments: 
            query += ' has:attachment'
            
        if custom_query: 
            query += f' ({custom_query})'
        
        print(f"Searching Gmail: {query}")
        
        try:
            results = self.service.users().messages().list(userId='me', q=query, maxResults=max_results).execute()
            messages = results.get('messages', [])
            
            if not messages:
                return {"success": True, "emails_found": 0, "filtered_count": 0, "filtered_out": 0, "results": []}
            
            email_results = []
            files_downloaded = 0
            filtered_out_count = 0
            
            for msg in messages:
                try:
                    message = self.service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
                    headers = message['payload']['headers']
                    
                    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No_Subject')
                    sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
                    date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
                    body = self._get_message_body(message['payload'])
                    
                    # LLM Relevance Check (No keyword pre-filtering)
                    if use_filtering and user_query:
                        relevance = self._is_relevant_via_llm(user_query, sender, subject, body)
                        
                        if not relevance["is_relevant"]:
                            filtered_out_count += 1
                            self.filtered_emails_log.append({
                                "subject": subject,
                                "sender": sender,
                                "reason": relevance["reason"],
                                "score": relevance["score"]
                            })
                            print(f"   ⊗ Filtered: {subject[:50]} (Score: {relevance['score']:.2f})")
                            continue
                        else:
                            print(f"   ✓ Relevant: {subject[:50]} (Score: {relevance['score']:.2f})")
                    
                    try:
                        dt = parsedate_to_datetime(date_str)
                        formatted_date = dt.strftime("%Y%m%d")
                    except:
                        formatted_date = datetime.now().strftime("%Y%m%d")

                    clean_sender = self._sanitize_filename(sender.split('<')[0])[:15]
                    clean_subject = self._sanitize_filename(subject)[:30]

                    attachments = []
                    if 'parts' in message['payload']:
                        for part in message['payload']['parts']:
                            if part.get('filename'):
                                original_filename = part['filename']
                                if original_filename.lower().endswith(('.pdf', '.png', '.jpg', '.jpeg', '.doc', '.docx')):
                                    if require_attachments and 'attachmentId' in part['body']:
                                        
                                        _, ext = os.path.splitext(original_filename)
                                        new_filename = f"{formatted_date}_{clean_sender}_{clean_subject}{ext}"
                                        
                                        filepath = self._download_attachment(msg['id'], part['body']['attachmentId'], new_filename)
                                        
                                        if filepath:
                                            attachments.append({"filename": new_filename, "filepath": filepath})
                                            files_downloaded += 1

                    email_results.append({
                        "id": msg['id'],
                        "subject": subject,
                        "sender": sender,
                        "date": date_str,
                        "body": body[:2000],
                        "attachments": attachments
                    })
                except Exception as msg_err:
                    print(f"Error processing message {msg.get('id')}: {msg_err}")
                    continue
            
            if self.filtered_emails_log:
                print(f"\n   📋 Filtered Out Emails Log:")
                for i, filtered in enumerate(self.filtered_emails_log[:5], 1):
                    print(f"      {i}. {filtered['subject'][:40]} - {filtered['reason'][:60]}")
                if len(self.filtered_emails_log) > 5:
                    print(f"      ... and {len(self.filtered_emails_log) - 5} more")
            
            return {
                "success": True,
                "emails_found": len(messages),
                "filtered_count": len(email_results),
                "filtered_out": filtered_out_count,
                "files_downloaded": files_downloaded,
                "filtered_log": self.filtered_emails_log,
                "results": email_results
            }
        
        except Exception as e:
            return {"success": False, "error": str(e), "results": []}


def scan_emails(date_from: str, 
                date_to: str, 
                custom_query: Optional[str] = None,
                user_query: Optional[str] = None,
                max_results: int = 50, 
                require_attachments: bool = True, 
                use_filtering: bool = True) -> Dict:
    scanner = EmailScanner()
    return scanner.scan(date_from, date_to, custom_query, user_query, max_results, require_attachments, use_filtering)