from flask import Flask, request, jsonify
from threading import Lock
import re
import requests

OWNER_MANUAL_URL = (
    "https://gitea-gitea.apps.cluster-vwppf.vwppf.sandbox2632.opentlc.com/"
    "starter/INSTRUCTIONS/raw/branch/master/resources/quantumpulse-3000.md"
)
app = Flask(__name__)

# Live accumulation
seq_to_instr = {}

# Frozen, persistent results after finalization
final_instructions = None   # list[str] once frozen
final_count = None          # int once frozen
finalized = False           # True after terminator finalizes the run

store_lock = Lock()

def repeating_unit_length(s: str) -> int:
    if not s:
        return 0
    pi = [0] * len(s)
    for i in range(1, len(s)):
        j = pi[i - 1]
        while j > 0 and s[i] != s[j]:
            j = pi[j - 1]
        if s[i] == s[j]:
            j += 1
        pi[i] = j
    n = len(s)
    period = n - pi[-1]
    return period if n % period == 0 else n

@app.route("/instruction", methods=["POST"])
def instruction():
    global final_instructions, final_count, finalized

    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json()

    if "seq" not in data or "instruction" not in data:
        return jsonify({"error": "JSON must include 'seq' and 'instruction'"}), 400

    try:
        seq = int(data["seq"])
    except (ValueError, TypeError):
        return jsonify({"error": "'seq' must be an integer"}), 400

    instr = data["instruction"]
    if not isinstance(instr, str):
        return jsonify({"error": "'instruction' must be a string"}), 400

    with store_lock:
        if finalized:
            # Ignore any further writes after we’ve frozen the result.
            return jsonify({"status": "ignored", "reason": "sequence finalized"}), 409

        # Upsert the step
        seq_to_instr[seq] = instr

        # If not the terminator, just acknowledge
        if instr != "":
            return jsonify({"status": "accepted", "seq": seq}), 202

        # Terminator received → check completeness for steps 1..(seq-1)
        final_seq = seq
        ordered = [seq_to_instr.get(i, "") for i in range(1, final_seq)]
        missing = [i for i, v in enumerate(ordered, start=1) if v == ""]

        if missing:
            # Don’t freeze; allow more steps to arrive
            return jsonify({
                "status": "incomplete",
                "final_seq": final_seq,
                "missing_count": len(missing),
                "missing_first_10": missing[:10],
            }), 409

        # Freeze results permanently
        final_instructions = ordered
        final_count = len(ordered)
        finalized = True

        # Optional: compute repeating length (kept for your visibility)
        message = "".join(ordered)
        base_len = repeating_unit_length(message)

        return jsonify({
            "status": "finalized",
            "final_seq": final_seq,
            "steps_counted": final_count,
            "message_length": len(message),
            "repeating_unit_length": base_len
        }), 200

@app.route("/count", methods=["GET"])
def count_instructions():
    with store_lock:
        if finalized:
            return jsonify({"instruction_count": final_count, "status": "final"}), 200
        # Live (pre-finalization) count excludes any empty strings
        live_count = sum(1 for v in seq_to_instr.values() if v != "")
        return jsonify({"instruction_count": live_count, "status": "in-progress"}), 200

@app.route("/instructions", methods=["GET"])
def list_instructions():
    """
    Returns instructions in order.
    - After finalization: persistent frozen list
    - Before finalization: current view with missing indices
    Query param: ?concat=true to include concatenated message
    """
    concat = request.args.get("concat", "false").lower() == "true"

    with store_lock:
        if finalized:
            resp = {
                "instructions": final_instructions,
                "status": "final",
                "count": final_count
            }
            if concat:
                resp["message"] = "".join(final_instructions)
            return jsonify(resp), 200

        if not seq_to_instr:
            return jsonify({"instructions": [], "status": "in-progress", "count": 0}), 200

        end = max(seq_to_instr.keys())
        ordered = [seq_to_instr.get(i, "") for i in range(1, end + 1)]
        missing = [i for i, v in enumerate(ordered, start=1) if v == ""]
        resp = {
            "instructions": ordered,
            "status": "in-progress",
            "count": sum(1 for v in ordered if v != ""),
            "missing": missing,
            "missing_count": len(missing),
        }
        if concat:
            resp["message"] = "".join(ordered)
        return jsonify(resp), 200

# Optional: explicit reset to start a brand-new run
@app.route("/reset", methods=["POST"])
def reset():
    global seq_to_instr, final_instructions, final_count, finalized
    with store_lock:
        seq_to_instr = {}
        final_instructions = None
        final_count = None
        finalized = False
    return jsonify({"status": "reset"}), 200

from flask import request, jsonify

@app.route("/chunks", methods=["GET"])
def chunks():
    """
    Reads the markdown Owner's Manual and splits it into fixed-size chunks.
    A 'paragraph' is any fragment of text separated by a blank line.
    Each chunk has `size` paragraphs (default 8); the final chunk may be smaller.

    Optional query params:
      - url: override the manual URL (defaults to OWNER_MANUAL_URL)
      - size: override chunk size (defaults to 8)
    """
    url = request.args.get("url", OWNER_MANUAL_URL)
    try:
        chunk_size = int(request.args.get("size", "8"))
        if chunk_size <= 0:
            raise ValueError
    except ValueError:
        return jsonify({"error": "size must be a positive integer"}), 400

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        text = resp.text
    except requests.RequestException as e:
        return jsonify({
            "error": "failed to fetch manual",
            "details": str(e),
            "url": url
        }), 502

    # Normalize newlines and trim
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()

    # If empty, return an empty set of chunks
    if not text:
        return jsonify({
            "url": url,
            "paragraph_count": 0,
            "chunk_size": chunk_size,
            "chunks_count": 0,
            "chunks": []
        }), 200

    # Split on one or more blank lines; treat whitespace-only lines as blank
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    para_count = len(paragraphs)

    # Build the actual chunks
    chunks_list = []
    for i in range(0, para_count, chunk_size):
        chunk_paras = paragraphs[i:i + chunk_size]
        chunks_list.append({
            "index": (i // chunk_size) + 1,           # 1-based index
            "start_paragraph": i + 1,                  # 1-based paragraph start
            "end_paragraph": i + len(chunk_paras),     # 1-based paragraph end
            "size": len(chunk_paras),
            "paragraphs": chunk_paras
        })

    return jsonify({
        "url": url,
        "paragraph_count": para_count,
        "chunk_size": chunk_size,
        "chunks_count": len(chunks_list),
        "chunks": chunks_list
    }), 200



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
