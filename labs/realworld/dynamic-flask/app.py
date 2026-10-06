from flask import Flask
app = Flask(__name__)

# Route registered via variable — path not a literal.
endpoint = "/dynamic"
app.add_url_rule(endpoint, "dyn", lambda: "ok")
