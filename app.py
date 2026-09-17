import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from openai import OpenAI
import json
import pg8000
from urllib.parse import urlparse, unquote
import ssl


def get_db_connection():
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    parsed = urlparse(database_url)

    if parsed.scheme not in ("postgres", "postgresql"):
        raise RuntimeError("Invalid DATABASE_URL scheme")

    return pg8000.connect(
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=(parsed.path or "").lstrip("/"),
    )

def initialize_database():
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                display_name TEXT,
                email TEXT,
                external_id TEXT UNIQUE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Upgrade an older users table without destroying existing data.
        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS display_name TEXT
        """)

        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS email TEXT
        """)

        cursor.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS external_id TEXT
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                title TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                memory TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.commit()
        cursor.close()

    finally:
        connection.close()


client = OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip())


def get_or_create_user(external_id, display_name=None, email=None):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        external_id = (external_id or "").strip()

        if not external_id:
            raise RuntimeError("external_id is required")

        cursor.execute("""
            SELECT id, display_name, email
            FROM users
            WHERE external_id = %s
            LIMIT 1
        """, (external_id,))

        row = cursor.fetchone()

        if row:
            user_id = row[0]

            if display_name or email:
                cursor.execute("""
                    UPDATE users
                    SET
                        display_name = COALESCE(%s, display_name),
                        email = COALESCE(%s, email)
                    WHERE id = %s
                """, (display_name, email, user_id))

                connection.commit()

            cursor.close()
            return user_id

        cursor.execute("""
            INSERT INTO users (display_name, email, external_id)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (display_name, email, external_id))

        user_id = cursor.fetchone()[0]

        connection.commit()
        cursor.close()

        return user_id

    finally:
        connection.close()


def get_conversation_owner(conversation_id):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            SELECT user_id
            FROM conversations
            WHERE id = %s
            LIMIT 1
        """, (conversation_id,))

        row = cursor.fetchone()

        cursor.close()

        return row[0] if row else None

    finally:
        connection.close()


def create_conversation(user_id, title):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO conversations (user_id, title)
            VALUES (%s, %s)
            RETURNING id
        """, (user_id, title[:200]))

        conversation_id = cursor.fetchone()[0]

        connection.commit()
        cursor.close()

        return conversation_id

    finally:
        connection.close()


def save_message(conversation_id, role, content):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO messages (conversation_id, role, content)
            VALUES (%s, %s, %s)
        """, (conversation_id, role, content))

        cursor.execute("""
            UPDATE conversations
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (conversation_id,))

        connection.commit()
        cursor.close()

    finally:
        connection.close()


NAIJASABI_INSTRUCTIONS = """
You are NAIJASABI AI, a full-purpose AI assistant built for Nigerians.

You are not a simple question-and-answer bot. Your job is to understand the
user's intent, follow the conversation naturally, reason through problems,
and provide useful answers across many areas.

GENERAL CAPABILITIES:
- Answer general knowledge questions.
- Explain difficult subjects clearly and step by step.
- Teach like a patient teacher when the user is learning.
- Help with mathematics, science, engineering, technology, coding, business,
  writing, research, planning, and everyday problems.
- Write, rewrite, summarize, translate, proofread, and improve text.
- Analyze information and compare options factually.
- Help users think through problems instead of simply giving shallow answers.
- Maintain continuity with the conversation provided to you.
- Ask a concise clarification only when the user's request is genuinely
  ambiguous.

NIGERIAN FOCUS:
- Understand Nigerian English and Nigerian Pidgin naturally.
- Understand Nigerian names, places, states, LGAs, institutions, cultures,
  languages, businesses, and everyday expressions.
- Give Nigeria-specific context when it is relevant.
- Treat all Nigerian ethnic groups, languages, cultures, religions,
  communities, and individuals respectfully.
- Do not stereotype Nigerians or invent cultural information.

ACCURACY:
- Never deliberately invent facts, statistics, quotations, laws, prices,
  news, people, places, events, or sources.
- When information may have changed, use web search when available and
  appropriate.
- For current news, government information, politics, elections, prices,
  weather, sports, events, laws, and other changing information, verify
  information rather than relying on memory.
- Clearly distinguish known facts from uncertainty.
- If reliable sources disagree, explain the disagreement.
- Never claim that you searched the web when you did not.

CONVERSATION:
- Pay attention to previous messages supplied in the conversation.
- Do not unnecessarily repeat questions the user has already answered.
- When the user refers to something earlier in the conversation, use that
  context when it is available.
- Respond naturally rather than sounding like a scripted chatbot.
- Match the user's language and communication style when appropriate.
- Nigerian Pidgin may be used naturally when the user uses it.

REASONING AND HELP:
- Think carefully before answering.
- Break complicated tasks into manageable steps.
- Give practical instructions when the user needs to perform something.
- For technical tasks, provide exact commands or code when appropriate.
- Do not pretend a task was completed when it was not.

PERSONALITY:
- Be helpful, calm, respectful, intelligent, practical, and honest.
- Be friendly without becoming unprofessional.
- Do not unnecessarily mention that you are an AI.
- Do not use generic error-style language when a useful explanation is
  possible.
- The goal is to provide a high-quality general AI assistant experience,
  with strong Nigerian understanding and context.

IMPORTANT:
NAIJASABI is intended to grow into a complete AI assistant. Do not behave as
though your abilities are limited to Nigerian questions. Nigeria is your
special focus, not your boundary.
"""



def needs_web_search(message):
    text = message.lower()

    current_words = [
        "latest",
        "today",
        "tonight",
        "tomorrow",
        "yesterday",
        "current",
        "recent",
        "news",
        "price",
        "prices",
        "cost",
        "weather",
        "forecast",
        "president",
        "governor",
        "election",
        "elections",
        "result",
        "results",
        "score",
        "scores",
        "match",
        "matches",
        "live",
        "now",
        "2026",
    ]

    return any(word in text for word in current_words)


class NaijaSabiAI(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS"
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS"
        )
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            self.send_json({
                "name": "NAIJASABI AI",
                "status": "online",
                "message": "NAIJASABI AI is ready"
            })
        elif self.path == "/test-auth":
            try:
                import os
                import urllib.request

                key = os.environ.get("OPENAI_API_KEY", "")
                req = urllib.request.Request(
                    "https://api.openai.com/v1/models",
                    headers={
                        "Authorization": f"Bearer {key}"
                    },
                    method="GET"
                )

                with urllib.request.urlopen(req, timeout=15) as r:
                    self.send_json({
                        "status": "success",
                        "http_status": r.status
                    })

            except Exception as e:
                print("AUTH TEST ERROR:", repr(e), flush=True)
                self.send_json({
                    "status": "failed",
                    "error": repr(e)
                }, 500)

        elif self.path == "/test-key":
            import os
            key = os.environ.get("OPENAI_API_KEY", "")
            self.send_json({
                "key_present": bool(key),
                "key_length": len(key),
                "key_starts_correctly": key.startswith("sk-")
            })

        elif self.path == "/test-network":
            try:
                import urllib.request
                req = urllib.request.Request(
                    "https://api.openai.com/v1/models",
                    method="GET"
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    self.send_json({
                        "status": "success",
                        "http_status": r.status
                    })
            except Exception as e:
                print("NETWORK TEST ERROR:", repr(e), flush=True)
                self.send_json({
                    "status": "failed",
                    "error": repr(e)
                }, 500)

        elif self.path == "/test-openai":
            try:
                test_response = client.responses.create(
                    model="gpt-5.6-luna",
                    input="Reply with exactly: OPENAI CONNECTION OK"
                )
                self.send_json({
                    "status": "success",
                    "reply": test_response.output_text
                })
            except Exception as e:
                print("OPENAI TEST ERROR:", str(e), flush=True)
                self.send_json({
                    "status": "failed",
                    "error": str(e)
                }, 500)
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if self.path != "/chat":
            self.send_json({"error": "Not found"}, 404)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))

            message = data.get("message", "").strip()
            history = data.get("history", [])
            conversation_id = data.get("conversation_id")
            external_id = data.get("external_id", "").strip()
            display_name = data.get("display_name", "").strip()
            email = data.get("email", "").strip()

            if not message:
                self.send_json({
                    "error": "Message is required"
                }, 400)
                return

            # Identify the user.
            # For now the mobile app supplies a persistent profile/device ID.
            # Real authenticated accounts will replace this with a verified
            # auth session later.
            if not external_id:
                self.send_json({
                    "error": "USER_ID_REQUIRED"
                }, 400)
                return

            user_id = get_or_create_user(
                external_id,
                display_name or None,
                email or None
            )

            # Continue the existing conversation when possible.
            if conversation_id:
                try:
                    conversation_id = int(conversation_id)
                except (TypeError, ValueError):
                    conversation_id = None

            if conversation_id:
                owner_id = get_conversation_owner(conversation_id)

                if owner_id != user_id:
                    conversation_id = None

            # Only create a database conversation when this is genuinely
            # a new chat.
            if not conversation_id:
                conversation_id = create_conversation(
                    user_id,
                    message
                )

            # Save the user's message permanently.
            save_message(
                conversation_id,
                "user",
                message
            )

            conversation = []

            if isinstance(history, list):

                # Keep the most recent 12 messages for better conversation continuity.
                recent_history = history[-12:]

                for item in recent_history:
                    if not isinstance(item, dict):
                        continue

                    role = item.get("role")
                    content = item.get("content")

                    if role not in ("user", "ai"):
                        continue

                    if not isinstance(content, str):
                        continue

                    content = content.strip()

                    if not content:
                        continue

                    # Prevent old conversations from becoming huge.
                    content = content[:1500]

                    conversation.append({
                        "role": (
                            "user"
                            if role == "user"
                            else "assistant"
                        ),
                        "content": content
                    })

            # Always make sure the newest user message is included.
            if not conversation or conversation[-1].get("content") != message:
                conversation.append({
                    "role": "user",
                    "content": message[:1500]
                })

            conversation = conversation[-10:]

            # Keep total conversation context small to reduce token usage.
            total_chars = 0
            limited_conversation = []
            for item in reversed(conversation):
                content = item.get("content", "")
                if total_chars + len(content) > 6000:
                    break
                limited_conversation.insert(0, item)
                total_chars += len(content)
            conversation = limited_conversation

            response_args = {
                "model": "gpt-5.6-luna",
                "instructions": NAIJASABI_INSTRUCTIONS,
                "input": conversation,
                "max_output_tokens": 2000,
            }

            # Only give the model web search when the question
            # appears to require current information.
            if needs_web_search(message):
                response_args["tools"] = [
                    {
                        "type": "web_search"
                    }
                ]

            # Make a small number of controlled retries for temporary
            # service failures. Do not retry indefinitely because repeated
            # requests can make rate limits worse.
            response = None
            last_error = None

            for attempt in range(2):
                try:
                    response = client.responses.create(**response_args)
                    break
                except Exception as request_error:
                    last_error = request_error
                    error_text = str(request_error)

                    if "rate_limit_exceeded" in error_text or "429" in error_text:
                        print(
                            f"OPENAI RATE LIMIT (attempt {attempt + 1})",
                            flush=True
                        )
                        if attempt == 0:
                            import time
                            time.sleep(2)
                            continue

                    raise

            if response is None:
                raise last_error

            reply = response.output_text

            # Save the AI response permanently.
            save_message(conversation_id, "assistant", reply)

            self.send_json({
                "reply": reply,
                "conversation_id": conversation_id
            })

        except Exception as e:

            error_text = str(e)
            print("OPENAI ERROR:", error_text, flush=True)

            if "rate_limit_exceeded" in error_text or "429" in error_text:
                self.send_json({
                    "error": "RATE_LIMIT",
                    "details": "NAIJASABI AI is temporarily busy because the AI service rate limit has been reached. Please try again later."
                }, 429)
                return

            self.send_json({
                "error": "AI request failed",
                "details": error_text
            }, 500)

port = int(os.environ.get("PORT", 8080))

try:
    initialize_database()
    print("DATABASE INITIALIZED", flush=True)
except Exception as e:
    print("DATABASE INITIALIZATION ERROR:", repr(e), flush=True)

server = HTTPServer(("0.0.0.0", port), NaijaSabiAI)

print("NAIJASABI AI is starting...")
print(f"Real AI backend running on port {port}")

server.serve_forever()
