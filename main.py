import os
from google import genai

# Client obyektini yaratish (API key muhit o'zgaruvchisidan yoki to'g'ridan-to'g mezoniy uzatiladi)
client = genai.Client(api_key="AIzaSyDL82cBQnkqhjKqXzSYvVQKaD17fhg2Hxk")

try:
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents='Test so\'rovi',
    )
    print("Status: Kalit faol va ishlayapti!")
    print("Javob:", response.text)
except Exception as e:
    print(f"Xatolik: {e}")