from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/instruction', methods=['POST'])
def instruction():
    # Ensure request is JSON
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()

    # Example: log or process the instruction
    print("Received instruction:", data)

    # Respond back
    return jsonify({"status": "success", "received": data}), 200


if __name__ == '__main__':
    # Host 0.0.0.0 allows access from external systems
    app.run(host="0.0.0.0", port=8080)
