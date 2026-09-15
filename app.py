import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from openai import OpenAI
import json

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip())

NAIJASABI_INSTRUCTIONS = """
You are NAIJASABI AI, a Nigerian-focused AI assistant.

Your purpose is to help people understand Nigeria and solve problems related
to Nigeria and everyday life.

CORE PRINCIPLES:
1. Be accurate, useful, clear, respectful, and honest.
2. Never invent facts, news, statistics, people, places, laws, prices, or events.
3. Use web search when the question requires current information.
4. For current Nigerian news, government information, policies, prices,
   events, sports, weather, and other changing information, verify information
   from reliable sources.
5. Clearly distinguish verified information from uncertainty or opinion.
6. If reliable sources disagree, explain the disagreement.
7. Understand Nigerian English and Nigerian Pidgin and use them when appropriate.
8. Treat Nigerian states, ethnic groups, languages, cultures, religions,
   communities, and people with respect.
9. Never claim to have searched the web unless web search was actually used.
10. If you cannot verify something, say so rather than inventing an answer.
11. Give practical answers whenever possible.
12. NAIJASABI should behave as a serious, trustworthy Nigerian AI assistant.
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

            if not message:
                self.send_json({
                    "error": "Message is required"
                }, 400)
                return

            conversation = []

            if isinstance(history, list):

                # Only keep the most recent 6 messages.
                recent_history = history[-6:]

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

            response_args = {
                "model": "gpt-5.6-luna",
                "instructions": NAIJASABI_INSTRUCTIONS,
                "input": conversation,
                "max_output_tokens": 800,
            }

            # Only give the model web search when the question
            # appears to require current information.
            if needs_web_search(message):
                response_args["tools"] = [
                    {
                        "type": "web_search"
                    }
                ]

            response = client.responses.create(**response_args)

            self.send_json({
                "reply": response.output_text
            })

        except Exception as e:

            error_text = str(e)
            import traceback; print("OPENAI ERROR:", type(e).__name__, error_text, flush=True); traceback.print_exc()

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

server = HTTPServer(("0.0.0.0", port), NaijaSabiAI)

print("NAIJASABI AI is starting...")
print(f"Real AI backend running on port {port}")

server.serve_forever()
