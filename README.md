Overview  
This project introduces a dual-layer verification pipeline:
1. Behavioral Verification (Process-level):
- Analyzes stroke timing, speed variance, path length, and drawing duration.
- Rejects bot-like patterns before invoking ML inference.
2. Image Recognition (Outcome-level):
- Uses a pre-trained MobileNetV2-based doodle classifier.
- Confirms that the final drawing matches the challenge prompt.
Only submissions passing both layers are accepted.

Architecture  
Frontend:
- HTML5 Canvas for drawing input
- JavaScript captures:
  - (x, y) coordinates
  - timestamps
  - speed variance
  - pressure data (Pointer Events API)
  - Sends Base64 image + path data via Fetch API  

Backend:
- Flask API for:
  - Challenge generation
  - CAPTCHA verification
  - Authentication & sessions
  - Dashboard analytics
  - Behavioral heuristics engine
  - TensorFlow/Keras model integration (inference only)
- MongoDB for persistent user data storage

Tech Stack  
Frontend:
- HTML5
- CSS3
- JavaScript (Canvas API, Fetch API)  

Backend:
- Python
- Flask
- TensorFlow / Keras (model inference)
- OpenCV & PIL (image preprocessing)
- MongoDB

Model Details
- Transfer Learning using MobileNetV2
- Trained on 1,000,000 Google QuickDraw samples
- Final Test Accuracy: 95.04%
- 20-class doodle classification

Running the Project
1. Clone the repository:
> git clone https://github.com/aditisinha835/Girl-Who-is-You-Doodle-CAPTCHA.git
cd Girl-Who-is-You-Doodle-CAPTCHA
3. Setup backend:
> cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
3. Ensure MongoDB is running
4. Start server:
> python app.py
5. Visit:
http://127.0.0.1:5000
