# 🎙️ GUS (General User System) – Voice-First Frame-Based Conversational Travel Assistant

GUS is a **Voice-First Frame-Based Conversational Travel Assistant** built with **HTML, CSS, JavaScript (frontend)** and **Python Flask (backend)**. Speech recognition and voice synthesis are **core capabilities** of GUS, allowing users to speak naturally or type at any step.

---

## 🌟 Voice-First Capabilities

1. **Real-Time Microphone Input (STT):** Click the glowing **`🎙️ Speak`** button to speak naturally. Speech is transcribed in real-time.
2. **Live Soundwave & Interim Visualizer:** Animated red pulsing ring, 5-bar dancing soundwave visualizer, and live interim transcript showing your words as you speak them.
3. **Natural Conversational Processing:** Speaks natural phrases like *"I want to take a flight"*, *"Round trip"*, *"From Mumbai"*, *"Going to New Delhi"*, *"Tomorrow"*, *"Two adult passengers"*, and *"Rahul Sharma and Priya Sharma"*. GUS automatically extracts and normalizes the underlying slots.
4. **Text-to-Speech (TTS):** GUS speaks its questions, prompts, and best-value recommendations aloud with natural intonation.
5. **Voice Toggle & Replay:** A one-click **`🔊 Voice On / Voice Off`** button in the header, plus a **`🔊 Listen`** button on every bot message to replay voice anytime.
6. **Voice Commands for Option Selection:** When results appear, users can simply say *"Select option 1"*, *"Choose IndiGo"*, or click to select a journey.
7. **Dual Voice & Text Support:** Seamlessly switch between speaking into the microphone and typing into the text input.

---

## 🔄 Travel Search Conversation Flow

1. **Greeting:** GUS welcomes the user via text and voice.
2. **Transport Type:** User speaks or chooses **Flight ✈️**, **Train 🚆**, or **Bus 🚌**.
3. **Journey Type:** User speaks or chooses **One-way ➡️** or **Round-trip 🔁**.
4. **Source & Destination:** Collects origin city/station and destination (cross-validated: cannot be identical).
5. **Travel Dates:** Prompts for departure date (and return date for round trips).
6. **Adult Passengers & Names:** Collects passenger count (1–9) and legal passenger names.
7. **Real External API Search:** Fetches actual available journeys from external travel APIs (Amadeus, Indian Railways, Bus partners).
8. **Display ALL Options:** Renders all options in chat with provider, departure, arrival, duration, stops, and total price.
9. **Compare & Select:** Highlights the **⭐ Best-Value Recommendation** and allows selection via voice command (*"Select option 1"*) or button click.
10. **Direct Provider Deep Link:** Hands off journey parameters directly to the official provider's booking portal (Google Flights, IRCTC, RedBus).

---

## 🔒 Integrity Guarantees

- **No Invented Availability or Prices:** If an external API credential is not configured, GUS explicitly discloses this and provides verified search links.
- **No Fake Bookings:** GUS never collects credit card payments or generates fake PNRs; all bookings are finalized on official provider portals.

---

## 🚀 Running the Project

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
```bash
copy .env.example .env
```
- For flights: Set `AMADEUS_CLIENT_ID` and `AMADEUS_CLIENT_SECRET`.
- For buses: Keep `BUS_USE_MOCK=true`.
- For multilingual voice input: Set `OPENAI_API_KEY`. GUS records audio with `MediaRecorder`
  and sends it to the Flask `/api/transcribe` endpoint, which calls multilingual Whisper
  with the selected `en`, `hi`, `bn`, `te`, or `ta` language code. Keep this key server-side.
- Voice output uses installed browser/OS voices. Install voices for each selected language;
  GUS reports an explicit error when a suitable voice is unavailable.

### 3. Start Server
```bash
python server.py
```
Open **`http://localhost:5001`** in a speech-enabled browser (Google Chrome, Microsoft Edge, or Safari).
