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

        if instr != "":
            return jsonify({"status": "accepted", "seq": seq}), 202

        final_seq = seq
        ordered = [seq_to_instr.get(i, "") for i in range(1, final_seq)]
        missing = [i for i, v in enumerate(ordered, start=1) if v == ""]
        message = "".join(ordered)

        if missing:
            result = {
                "status": "incomplete",
                "final_seq": final_seq,
                "missing_count": len(missing),
                "missing_first_10": missing[:10],
                "message_length": len(message),
            }
            return jsonify(result), 409

        base_len = repeating_unit_length(message)
        result = {
            "status": "complete",
            "final_seq": final_seq,
            "steps_counted": final_seq - 1,
            "message_length": len(message),
            "repeating_unit_length": base_len,
        }

        seq_to_instr.clear()
        return jsonify(result), 200

@app.route("/count", methods=["GET"])
def count_instructions():
    with store_lock:
        # Count only non-empty instructions (exclude the terminator if received early)
        count = sum(1 for instr in seq_to_instr.values() if instr != "")
    return jsonify({"instruction_count": count}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
