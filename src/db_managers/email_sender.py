import smtplib
import os
from email.mime.text import MIMEText
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

class EmailSender:
    def __init__(self):
        self.sender_email = os.getenv("GMAIL_ADDRESS")
        self.sender_password = os.getenv("GMAIL_PASSWORD")
        self.smtp_server = 'smtp.gmail.com'
        self.smtp_port = 465
        self.server = None
        self._connect_smtp()

    def _connect_smtp(self):
        """Connect to the Gmail SMTP server."""
        try:
            self.server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            self.server.login(self.sender_email, self.sender_password)
            print(f"Connected to Gmail SMTP server: {self.smtp_server}:{self.smtp_port}")
        except Exception as e:
            print(f"Error connecting to Gmail SMTP server: {e}")
            self.server = None

    def _disconnect_smtp(self):
        """Disconnect from the Gmail SMTP server."""
        if self.server:
            try:
                self.server.quit()
                print("Disconnected from Gmail SMTP server.")
            except Exception as e:
                print(f"Error disconnecting from Gmail SMTP server: {e}")
            finally:
                self.server = None

    def send_email(self, recipient_email, subject, body, html=False):
        """Send an email using the initialized Gmail server."""
        if not self.server:
            print("Gmail SMTP server not connected. Attempting to reconnect...")
            self._connect_smtp()
            if not self.server:
                print("Failed to connect to Gmail SMTP server. Cannot send email.")
                return False

        try:
            if html:
                msg = MIMEText(body, 'html')
            else:
                msg = MIMEText(body, 'plain')

            msg['Subject'] = subject
            msg['From'] = self.sender_email
            msg['To'] = recipient_email

            self.server.sendmail(self.sender_email, recipient_email, msg.as_string())
            print(f"Email sent successfully to {recipient_email}")
            return True
        except Exception as e:
            print(f"Error sending email to {recipient_email}: {e}")
            return False

    def send_welcome_email(self,recipient_email,username, email):
        """Send a welcome email to the recipient."""
        subject = "Welcome to Grocery Assistant App!"
        body = f"""
        <html>
            <body>
                
                <p>Hi {username or email},</p>

                <p>Welcome to the <b>Smart Grocery</b> family! We're thrilled to have you join our community dedicated to making grocery shopping easier, smarter, and more efficient.</p>

                <h3>Get ready to experience features like:</h3>
                <ul>
                    <li><b>Effortless Receipt Scanning:</b> Upload your receipts and let us handle the itemizing.</li>
                    <li><b>Intelligent Stock Tracking:</b> Keep tabs on your groceries and avoid unnecessary purchases.</li>
                    <li><b>Smart Chatbot Assistance:</b> Ask questions about your groceries, expiration dates, and more!</li>
                    <li><b>Insightful Analytics:</b> Understand your spending habits and discover savings.</li>
                    <li><b>Personalized Recommendations:</b> Recipes and suggestions based on your stock (coming soon!).</li>
                </ul>

                <p>We're constantly working on new features to enhance your experience. Feel free to explore the app and share any feedback or suggestions – we'd love to hear from you!</p>

                <p>Happy Shopping!</p>

                <p><b>The Smart Grocery Team</b><br>
                
            </body>
        </html>
        """
        return self.send_email(recipient_email,subject, body, html=True)

    def send_grocery_summary(self, app_context, recipient_email, low_stock_items=None, expiring_soon=None):
        """Sends a daily grocery summary email."""
        with app_context:  # Flask app context, if needed
            email_sender = EmailSender()

            now = datetime.now()
            subject = f"Your Daily Smart Grocery Summary - {now.strftime('%Y-%m-%d')}"

            body = f"""
            <html>
                <body>
                    <p>Good morning!</p>

                    <p>Here's your daily summary from <b>Smart Grocery</b> for {now.strftime('%Y-%m-%d')}:</p>

                    <h3>Items Low in Stock:</h3>
                    <ul>
            """
            if low_stock_items:
                for item in low_stock_items:
                    body += f"<li>{item}</li>"
            else:
                body += "<li>No items are currently low in stock.</li>"

            body += """
                    </ul>
                    <h3>Items Expiring Soon:</h3>
                    <ul>
            """
            if expiring_soon:
                for item in expiring_soon:
                    body += f"<li>{item}</li>"
            else:
                body += "<li>No items are expiring soon.</li>"

            body += """
                    </ul>

                    <p>Stay smart with your groceries!</p>

                    <p><b>The Smart Grocery Team</b></p>
                </body>
            </html>
            """

            try:
                email_sender.send_email(recipient_email, subject, body, html=True)
                print(f"Daily grocery summary email sent to {recipient_email} at {now.strftime('%H:%M:%S')}")
            except Exception as e:
                print(f"Error sending daily grocery summary email: {e}")

    def __del__(self):
        """Ensure the SMTP connection is closed when the object is destroyed."""
        self._disconnect_smtp()
