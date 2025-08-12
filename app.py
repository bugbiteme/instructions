# app.py
from flask import Flask, request, jsonify
from threading import Lock

app = Flask(__name__)

seq_to_instr = {}
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
        seq_to_instr[seq] = instr

        # If terminator not received, just accept
        if instr != "":
            return jsonify({"status": "accepted", "seq": seq}), 202

        # Terminator received → compute result if complete
        final_seq = seq
        ordered = [seq_to_instr.get(i, "") for i in range(1, final_seq)]
        missing = [i for i, v in enumerate(ordered, start=1) if v == ""]
        message = "".join(ordered)

        if missing:
            return jsonify({
                "status": "incomplete",
                "final_seq": final_seq,
                "missing_count": len(missing),
                "missing_first_10": missing[:10],
                "message_length": len(message),
            }), 409

        base_len = repeating_unit_length(message)
        result = {
            "status": "complete",
            "final_seq": final_seq,
            "steps_counted": final_seq - 1,
            "message_length": len(message),
            "repeating_unit_length": base_len,
        }

        # Reset for next run
        seq_to_instr.clear()
        return jsonify(result), 200

@app.route("/count", methods=["GET"])
def count_instructions():
    with store_lock:
        count = sum(1 for instr in seq_to_instr.values() if instr != "")
    return jsonify({"instruction_count": count}), 200

@app.route("/instructions", methods=["GET"])
def list_instructions():
    """
    Returns all instructions in order.
    - If a terminator "" was received, returns steps 1..(terminator_seq-1)
    - Otherwise returns steps 1..max_seq_seen (missing steps reported)
    """
    with store_lock:
        if not seq_to_instr:
            return jsonify({
                "instructions": [],
                "final_seq_basis": None,
                "missing": [],
                "missing_count": 0
            }), 200

        # Determine end of sequence
        terminators = [s for s, v in seq_to_instr.items() if v == ""]
        if terminators:
            end = max(terminators) - 1  # exclude terminator
            basis = "terminator"
        else:
            end = max(seq_to_instr.keys())
            basis = "max_seen"

        # Build ordered list and detect missing
        ordered = [seq_to_instr.get(i, "") for i in range(1, end + 1)]
        missing = [i for i, v in enumerate(ordered, start=1) if v == ""]

        return jsonify({
            "instructions": ordered,              # in order
            "final_seq_basis": basis,            # "terminator" or "max_seen"
            "end_seq": end,
            "missing": missing,
            "missing_count": len(missing)
        }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
