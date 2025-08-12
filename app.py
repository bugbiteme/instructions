from flask import Flask, request, jsonify
from threading import Lock

app = Flask(__name__)

seq_to_instr = {}
final_instructions = None   # persistent final ordered sequence
final_count = None          # persistent final count
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
    global final_instructions, final_count

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

        # Not the terminator, just ack
        if instr != "":
            return jsonify({"status": "accepted", "seq": seq}), 202

        # Terminator received → finalize if complete
        final_seq = seq
        ordered = [seq_to_instr.get(i, "") for i in range(1, final_seq)]
        missing = [i for i, v in enumerate(ordered, start=1) if v == ""]

        if missing:
            return jsonify({
                "status": "incomplete",
                "final_seq": final_seq,
                "missing_count": len(missing),
                "missing_first_10": missing[:10],
                "message_length": sum(len(x) for x in ordered),
            }), 409

        # Persist final values
        final_instructions = ordered.copy()
        final_count = len(final_instructions)

        # Optionally compute repeating length (unchanged)
        message = "".join(ordered)
        base_len = repeating_unit_length(message)

        # Clear live buffer for the next run (keeps the persisted finals)
        seq_to_instr.clear()

        return jsonify({
            "status": "complete",
            "final_seq": final_seq,
            "steps_counted": final_count,
            "message_length": len(message),
            "repeating_unit_length": base_len
        }), 200

@app.route("/count", methods=["GET"])
def count_instructions():
    """
    Returns instruction count.
    - Default: persistent final count if available (status=final).
    - Use ?current=true to force current in-progress count (status=in-progress).
    """
    current = request.args.get("current", "false").lower() == "true"
    with store_lock:
        if not current and final_count is not None:
            return jsonify({"instruction_count": final_count, "status": "final"}), 200

        # Count live, non-empty instructions in the current run
        live_count = sum(1 for instr in seq_to_instr.values() if instr != "")
        return jsonify({"instruction_count": live_count, "status": "in-progress"}), 200

@app.route("/instructions", methods=["GET"])
def list_instructions():
    """
    Returns ordered instructions.
    - If finalized, returns the persisted final set: status=final
    - Otherwise, returns current in-progress view with missing indices
    - Add ?concat=true to include the concatenated message string
    """
    concat = request.args.get("concat", "false").lower() == "true"

    with store_lock:
        if final_instructions is not None:
            resp = {
                "instructions": final_instructions,
                "status": "final"
            }
            if concat:
                resp["message"] = "".join(final_instructions)
            return jsonify(resp), 200

        if not seq_to_instr:
            return jsonify({"instructions": [], "status": "in-progress"}), 200

        end = max(seq_to_instr.keys())
        ordered = [seq_to_instr.get(i, "") for i in range(1, end + 1)]
        missing = [i for i, v in enumerate(ordered, start=1) if v == ""]
        resp = {
            "instructions": ordered,
            "status": "in-progress",
            "missing": missing,
            "missing_count": len(missing)
        }
        if concat:
            resp["message"] = "".join(ordered)
        return jsonify(resp), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
