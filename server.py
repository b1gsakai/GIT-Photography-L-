import json
import base64
import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


DATA_FILE = "food_data.json"
CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_MODEL = os.environ.get("CEREBRAS_MODEL", "gpt-oss-120b")
SUMMARY_LOCK = Lock()
JWKS_LOCK = Lock()
JWKS_CACHE = {"expires_at": 0, "keys": []}
CLERK_PUBLISHABLE_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")

FOOD_ITEMS = [
    "Buttermilk Pancakes",
    "Smoothie Bowl",
    "Full English Breakfast",
    "Creamy Baked Mac and Cheese",
    "Vegetarian Bean and Rice Burrito",
    "Air Fryer Grilled Cheese",
    "Delicious Pizza",
    "Bacon Cheese Burgers and Chili Cheese Fries",
    "Hot Dogs on Colored Plates",
]

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as data_file:
            return json.load(data_file)
    except (OSError, json.JSONDecodeError):
        return {}


food_data = load_data()


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as data_file:
        json.dump(food_data, data_file, indent=2)


def init_food_items():
    changed = False
    for food_name in FOOD_ITEMS:
        if food_name not in food_data:
            food_data[food_name] = {
                "comments": [],
                "ratings": [],
                "community_note": "No reviews yet. Be the first to rate and comment!",
            }
            changed = True
    if changed or not os.path.exists(DATA_FILE):
        save_data()


def fallback_summary(food_name):
    item = food_data[food_name]
    ratings = item["ratings"]
    comments = item["comments"]
    if not ratings and not comments:
        return f"No reviews yet for {food_name}. Be the first to rate and comment!"
    average = sum(ratings) / len(ratings) if ratings else 0
    return f"Community rating: {average:.1f}/5 from {len(ratings)} ratings and {len(comments)} comments."


def generate_summary_with_cerebras(food_name):
    item = food_data[food_name]
    ratings = item["ratings"]
    comments = item["comments"]
    if not ratings and not comments:
        return fallback_summary(food_name)

    api_key = os.environ.get("CEREBRAS_SECRET")
    if not api_key:
        return fallback_summary(food_name)

    average = sum(ratings) / len(ratings) if ratings else 0
    comment_lines = "\n".join(
        f"- {comment.get('text', '')}" for comment in comments
    )
    prompt = (
        "Summarize community feedback for this food item in one or two sentences. "
        "Mention the average rating and the main themes without inventing details.\n\n"
        f"Food: {food_name}\nAverage rating: {average:.1f}/5\n"
        f"Comments:\n{comment_lines}"
    )
    payload = {
        "model": CEREBRAS_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 200,
    }
    request = Request(
        CEREBRAS_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; FoodGallery/1.0)",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        summary = result.get("choices", [{}])[0].get("message", {}).get("content")
        return summary.strip() if summary else fallback_summary(food_name)
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as error:
        print(f"Cerebras summary unavailable: {error}", flush=True)
        return fallback_summary(food_name)


def update_cached_community_note(food_name):
    try:
        with SUMMARY_LOCK:
            food_data[food_name]["community_note"] = generate_summary_with_cerebras(
                food_name
            )
            save_data()
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"Could not save community note: {error}", flush=True)


def decode_base64url(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def get_clerk_jwks():
    now = time.time()
    if JWKS_CACHE["expires_at"] > now:
        return JWKS_CACHE["keys"]
    if not CLERK_SECRET_KEY:
        return []

    request = Request(
        "https://api.clerk.com/v1/jwks",
        headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
    )
    with JWKS_LOCK:
        if JWKS_CACHE["expires_at"] > time.time():
            return JWKS_CACHE["keys"]
        with urlopen(request, timeout=10) as response:
            keys = json.loads(response.read().decode("utf-8")).get("keys", [])
        JWKS_CACHE["keys"] = keys
        JWKS_CACHE["expires_at"] = time.time() + 3600
        return keys


def verify_clerk_session_token(token):
    try:
        header_part, payload_part, signature_part = token.split(".")
        header = json.loads(decode_base64url(header_part))
        payload = json.loads(decode_base64url(payload_part))
        if header.get("alg") != "RS256":
            return None

        key = next(
            (candidate for candidate in get_clerk_jwks() if candidate.get("kid") == header.get("kid")),
            None,
        )
        if not key:
            return None

        modulus = int.from_bytes(decode_base64url(key["n"]), "big")
        exponent = int.from_bytes(decode_base64url(key["e"]), "big")
        signature = int.from_bytes(decode_base64url(signature_part), "big")
        decoded_signature = pow(signature, exponent, modulus).to_bytes(
            (modulus.bit_length() + 7) // 8,
            "big",
        )
        digest = hashlib.sha256(
            f"{header_part}.{payload_part}".encode("ascii")
        ).digest()
        digest_info = bytes.fromhex(
            "3031300d060960864801650304020105000420"
        ) + digest
        expected = b"\x00\x01" + b"\xff" * (
            len(decoded_signature) - len(digest_info) - 3
        ) + b"\x00" + digest_info
        if not hmac.compare_digest(decoded_signature, expected):
            return None

        now = int(time.time())
        if payload.get("exp") is not None and now >= int(payload["exp"]):
            return None
        if payload.get("nbf") is not None and now < int(payload["nbf"]):
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        return {"user_id": user_id, "session_id": payload.get("sid")}
    except (
        KeyError,
        ValueError,
        TypeError,
        IndexError,
        json.JSONDecodeError,
        OSError,
        HTTPError,
        URLError,
        TimeoutError,
    ):
        return None


def authenticated_user(handler):
    cookies = SimpleCookie(handler.headers.get("Cookie", ""))
    session_cookie = cookies.get("__session")
    token = session_cookie.value if session_cookie else ""
    if not token:
        authorization = handler.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization[7:].strip()
    return verify_clerk_session_token(token) if token else None


def validate_review_payload(payload):
    rating = payload.get("rating")
    if (
        not isinstance(rating, int)
        or isinstance(rating, bool)
        or not 1 <= rating <= 5
    ):
        return None, "Choose a star rating from 1 to 5."

    text = str(payload.get("text", "")).strip()
    if not text:
        return None, "Write a comment before submitting your review."
    if len(text) > 2_000:
        return None, "Comments must be 2,000 characters or fewer."

    return {"rating": rating, "text": text}, None


def ensure_food(food_name):
    if food_name not in food_data:
        food_data[food_name] = {
            "comments": [],
            "ratings": [],
            "community_note": "No reviews yet. Be the first to rate and comment!",
        }
        save_data()


class GalleryHandler(SimpleHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 16_384:
            raise ValueError("Request is too large")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def food_name_from_path(self):
        prefix = "/api/food/"
        return unquote(urlparse(self.path).path[len(prefix):])

    def send_index(self):
        try:
            body = Path("index.html").read_text(encoding="utf-8")
        except OSError:
            self.send_error(404)
            return
        body = body.replace(
            "__CLERK_PUBLISHABLE_KEY__",
            json.dumps(CLERK_PUBLISHABLE_KEY),
        )
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self.send_index()
            return
        if path == "/api/foods":
            self.send_json(200, food_data)
            return
        if path == "/api/auth/me":
            user = authenticated_user(self)
            if not user:
                self.send_json(401, {"authenticated": False})
                return
            self.send_json(200, {"authenticated": True, "user_id": user["user_id"]})
            return
        if path.startswith("/api/food/"):
            food_name = self.food_name_from_path()
            if not food_name:
                self.send_json(400, {"error": "Food name is required"})
                return
            ensure_food(food_name)
            self.send_json(200, food_data[food_name])
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/food/"):
            self.send_json(404, {"error": "Not found"})
            return

        parts = path.split("/")
        if len(parts) < 5:
            self.send_json(404, {"error": "Not found"})
            return

        food_name = unquote("/".join(parts[3:-1]))
        action = parts[-1]
        if not food_name:
            self.send_json(400, {"error": "Food name is required"})
            return
        ensure_food(food_name)

        try:
            payload = self.read_json()
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "Valid JSON is required"})
            return

        if action in ("rate", "comment", "review"):
            if action != "review":
                self.send_json(
                    400,
                    {
                        "error": (
                            "Ratings and comments must be submitted together "
                            "using the review endpoint."
                        )
                    },
                )
                return

            auth_user = authenticated_user(self)
            if not auth_user:
                self.send_json(
                    401,
                    {"error": "Sign in or create an account before posting a review."},
                )
                return

            review, error = validate_review_payload(payload)
            if error:
                self.send_json(400, {"error": error})
                return

            comment = {
                "id": str(uuid.uuid4()),
                "text": review["text"],
                "rating": review["rating"],
                "user_id": auth_user["user_id"],
                "user_name": str(payload.get("user_name") or "Member").strip(),
                "timestamp": datetime.now().isoformat(),
            }
            food_data[food_name]["ratings"].append(review["rating"])
            food_data[food_name]["comments"].append(comment)

            # Persist the review before making the external request so the
            # user's rating and comment survive even if AI is unavailable.
            food_data[food_name]["community_note"] = fallback_summary(food_name)
            save_data()
            Thread(
                target=update_cached_community_note,
                args=(food_name,),
                daemon=True,
            ).start()
            ratings = food_data[food_name]["ratings"]
            self.send_json(
                202,
                {
                    "message": "Review submitted; community note is updating",
                    "comment": comment,
                    "rating": review["rating"],
                    "avg_rating": sum(ratings) / len(ratings),
                    "community_note": food_data[food_name]["community_note"],
                    "community_note_pending": True,
                },
            )
            return

        if action == "refresh":
            self.send_json(
                200,
                {
                    "community_note": food_data[food_name]["community_note"],
                    "message": "Community note is refreshed when a new review is submitted.",
                },
            )
            return

        self.send_json(404, {"error": "Not found"})


if __name__ == "__main__":
    init_food_items()
    server = ThreadingHTTPServer(("0.0.0.0", 5000), GalleryHandler)
    print("Serving food gallery on 0.0.0.0 port 5000", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()