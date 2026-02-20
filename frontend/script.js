// --- Global variables ---
let currentChallenge = "";
let currentToken = "";
let pathData = [];
let drawing = false;
let startTime = 0;
let lastX = 0, lastY = 0;

const baseUrl = "http://127.0.0.1:5000";
const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d", { willReadFrequently: true });
const result = document.getElementById("result");
const emailField = document.getElementById("email");
const passwordField = document.getElementById("password");

// --- Canvas Setup ---
ctx.fillStyle = "#FFF";
ctx.fillRect(0, 0, canvas.width, canvas.height);

// --- Event Listeners ---
canvas.addEventListener("mousedown", startDrawing);
canvas.addEventListener("mouseup", stopDrawing);
canvas.addEventListener("mouseout", stopDrawing);
canvas.addEventListener("mousemove", draw);

// Touch events for mobile
canvas.addEventListener("touchstart", (e) => { e.preventDefault(); startDrawing(e.touches[0]); }, false);
canvas.addEventListener("touchend", (e) => { e.preventDefault(); stopDrawing(); }, false);
canvas.addEventListener("touchmove", (e) => { e.preventDefault(); draw(e.touches[0]); }, false);

// --- Drawing Functions ---
function getMousePos(evt) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return {
    x: (evt.clientX - rect.left) * scaleX,
    y: (evt.clientY - rect.top) * scaleY,
    t: Date.now(),
    p: evt.pressure || 0.5 // Get pressure, or default to 0.5
  };
}

function startDrawing(e) {
  if (drawing) return;
  drawing = true;
  startTime = Date.now();
  const pos = getMousePos(e);
  [lastX, lastY] = [pos.x, pos.y];
  pathData.push(pos);
}

function draw(e) {
  if (!drawing) return;
  const pos = getMousePos(e);
  ctx.lineWidth = 10;
  ctx.lineCap = "round";
  ctx.strokeStyle = "#000";
  ctx.beginPath();
  ctx.moveTo(lastX, lastY);
  ctx.lineTo(pos.x, pos.y);
  ctx.stroke();
  [lastX, lastY] = [pos.x, pos.y];
  pathData.push(pos);
}

function stopDrawing() {
  drawing = false;
}

function clearCanvas() {
  ctx.fillStyle = "#FFF";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  pathData = []; // Clear the path data
}

// --- API Functions ---
async function getNewChallenge() {
  try {
    const res = await fetch(`${baseUrl}/get_captcha`, { credentials: "include" });
    const data = await res.json();
    if (data.success) {
      currentChallenge = data.challenge;
      currentToken = data.token;
      document.getElementById("challenge").innerText = `Draw ${currentChallenge}`;
    } else {
      document.getElementById("challenge").innerText = "Could not load challenge.";
    }
  } catch (err) {
    document.getElementById("challenge").innerText = "Server connection error.";
  }
  result.innerText = "";
  clearCanvas();
}

async function submitCaptcha() {
  const email = emailField.value.trim();
  const password = passwordField.value.trim();
  const drawingTime = Date.now() - startTime;
  const image = canvas.toDataURL("image/png");

  if (!email || !password) {
    Swal.fire("Missing Info", "Please enter your email and password.", "warning");
    return;
  }
  if (pathData.length < 15) {
    Swal.fire("Drawing Too Simple", "Please provide a more complete drawing.", "warning");
    return;
  }

  result.innerText = "Logging in...";
  result.style.color = "black";

  try {
    // Step 1: Login
    const loginRes = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, password })
    });
    const loginData = await loginRes.json();

    if (!loginData.success) {
      Swal.fire("Login Failed", loginData.message, "error");
      result.innerText = "";
      getNewChallenge(); // Get a new token, as the old one is likely invalid
      return;
    }

    // Step 2: Verify CAPTCHA
    result.innerText = "Verifying CAPTCHA...";
    const verifyRes = await fetch(`${baseUrl}/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        image: image,
        token: currentToken,
        drawingTime: drawingTime,
        pathData: pathData
      })
    });

    const verifyData = await verifyRes.json();

    if (verifyData.success) {
      Swal.fire({
        icon: "success",
        title: "CAPTCHA Verified!",
        text: `You successfully drew ${currentChallenge}!`,
        confirmButtonText: "Continue"
      }).then(() => {
        window.location.href = "/dashboard";
      });
    } else {
      Swal.fire({
        icon: "error",
        title: "Invalid CAPTCHA",
        text: verifyData.message || `You did not draw ${currentChallenge}. Try again!`,
        confirmButtonText: "Retry"
      }).then(() => {
        getNewChallenge(); // Get a new challenge and token
      });
    }
  } catch (err) {
    console.error("Error:", err);
    result.innerText = "Failed to connect to server.";
    result.style.color = "red";
  }
}

// Load first challenge on page load
window.onload = getNewChallenge;