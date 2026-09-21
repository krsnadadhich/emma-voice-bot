import os

from dotenv import load_dotenv

load_dotenv()

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_API_KEY = os.environ.get("TWILIO_API_KEY", "")
TWILIO_API_SECRET = os.environ.get("TWILIO_API_SECRET", "")
TWILIO_TWIML_APP_SID = os.environ.get("TWILIO_TWIML_APP_SID", "")

MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "emma_demo")

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

COMPANY_PROFILE = os.environ.get("COMPANY_PROFILE", "deliverail")

PORT = int(os.environ.get("PORT", "5000"))
