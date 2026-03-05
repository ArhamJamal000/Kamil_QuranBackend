import os
import google.generativeai as genai
from dotenv import load_dotenv

def test_gemini_api():
    print("Loading environment variables...")
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY not found in .env file or environment variables.")
        return

    print("Configuring Google Generative AI...")
    genai.configure(api_key=api_key)

    try:
        print("Sending test prompt to gemini-2.5-flash...")
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        response = model.generate_content("Please reply with exactly 'Hello, Gemini is working properly!' and nothing else.")
        
        print("\n✅ Success! Gemini API responded:")
        print("-" * 40)
        print(response.text.strip())
        print("-" * 40)
    except Exception as e:
        print(f"\n❌ Error occurred while listing models:")
        print(str(e))

if __name__ == "__main__":
    test_gemini_api()
