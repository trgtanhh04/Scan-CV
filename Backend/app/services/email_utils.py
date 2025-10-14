import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
# import os

# SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
# SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
# SENDER_EMAIL = os.getenv("SENDER_EMAIL", "phatcolab0209@gmail.com")
# SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "ouzo dgjn lncm chib")

SMTP_SERVER =  "smtp.gmail.com"
SMTP_PORT =  465
SENDER_EMAIL = "phatcolab0209@gmail.com"
SENDER_PASSWORD = "ouzo dgjn lncm chib"

def send_email(recipient_email: str, subject: str, html_body: str):
    """Gửi email HTML qua Gmail SMTP"""
    msg = MIMEMultipart("alternative")
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    try:
        # with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        #     server.starttls()
        #     server.login(SENDER_EMAIL, SENDER_PASSWORD)
        #     server.send_message(msg)
        with smtplib.SMTP_SSL(SMTP_SERVER, 465) as smtp_server:
            smtp_server.login(SENDER_EMAIL, SENDER_PASSWORD)
            smtp_server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send to {recipient_email}: {e}")
        return False