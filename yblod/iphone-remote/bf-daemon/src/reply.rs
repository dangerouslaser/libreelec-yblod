//! The JSON-line sockets' answers (tvd.sock, speakerd.sock): the result of a
//! command, or why it failed, with the command and its id (when it had one).

use serde_json::{Value, json};

/// {"reply": REPLY, "cmd": CMD[, "id": ID]}
pub fn reply_line(reply: &Value, cmd: &str, id: Option<&Value>) -> String {
    line(json!({ "reply": reply, "cmd": cmd }), id)
}

/// {"error": ERROR, "cmd": CMD[, "id": ID]}
pub fn error_line(error: &str, cmd: &str, id: Option<&Value>) -> String {
    line(json!({ "error": error, "cmd": cmd }), id)
}

fn line(mut v: Value, id: Option<&Value>) -> String {
    if let Some(id) = id {
        v["id"] = id.clone();
    }
    v.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lines() {
        assert_eq!(reply_line(&json!(3), "volume", None), r#"{"cmd":"volume","reply":3}"#);
        assert_eq!(error_line("no TV", "power", Some(&json!(7))), r#"{"cmd":"power","error":"no TV","id":7}"#);
    }
}
