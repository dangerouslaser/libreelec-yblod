//! The phone's keyboard ("remote text input", RTI): the payloads of
//! `_tiStart`'s answer, `_tiStarted` and `_tiC`, NSKeyedArchiver binary
//! property lists. Written from pyatv's description of them (its
//! `keyed_archiver.py` and `plist_payloads/`, MIT) and CompanionGames'
//! notes on a server-started typing session (facts only: AGPL).
//!
//! An archive is `{"$archiver", "$version", "$top": {name: UID},
//! "$objects": [...]}`: object 0 is "$null", others are strings, data,
//! numbers or dictionaries whose values are UIDs of other objects (and
//! `$class`, a UID of `{"$classname", "$classes"}`).
//!
//! What we send (a text field has the focus): `$top` = `sessionUUID` (16
//! bytes of data, this typing session's), `documentState` (an
//! RTIDocumentState whose `docSt` is a TIDocumentState with
//! `contextBeforeInput`: the field's text) and `documentTraits` (an
//! RTIDocumentTraits: the app's name and ids, and TITextInputTraits).
//!
//! What we read (`_tiC`): `$top.textOperations`, an RTITextOperations with
//! `keyboardOutput` (TIKeyboardOutput: `insertionText`, `deletionCount`)
//! and/or `textToAssert` (the whole text, replacing the field's).

use plist::{Dictionary, Uid, Value};

/// Builds an archive's object table.
struct Archive {
    objects: Vec<Value>,
}

impl Archive {
    fn new() -> Self {
        Self { objects: vec![Value::String("$null".into())] }
    }

    fn add(&mut self, v: Value) -> Value {
        self.objects.push(v);
        Value::Uid(Uid::new(self.objects.len() as u64 - 1))
    }

    fn class(&mut self, name: &str) -> Value {
        let mut d = Dictionary::new();
        d.insert("$classname".into(), Value::String(name.into()));
        d.insert("$classes".into(), Value::Array(vec![Value::String(name.into()), Value::String("NSObject".into())]));
        self.add(Value::Dictionary(d))
    }

    fn object(&mut self, class: &str, fields: Vec<(&str, Value)>) -> Value {
        let class = self.class(class);
        let mut d = Dictionary::new();
        for (k, v) in fields {
            d.insert(k.into(), v);
        }
        d.insert("$class".into(), class);
        self.add(Value::Dictionary(d))
    }

    fn finish(self, archiver: &str, top: Vec<(&str, Value)>) -> Vec<u8> {
        let mut t = Dictionary::new();
        for (k, v) in top {
            t.insert(k.into(), v);
        }
        let mut root = Dictionary::new();
        root.insert("$version".into(), Value::Integer(100000.into()));
        root.insert("$archiver".into(), Value::String(archiver.into()));
        root.insert("$top".into(), Value::Dictionary(t));
        root.insert("$objects".into(), Value::Array(self.objects));
        let mut out = Vec::new();
        // Writing to a Vec doesn't fail.
        let _ = plist::to_writer_binary(&mut out, &Value::Dictionary(root));
        out
    }
}

/// The field the keyboard is for: what the phone shows.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Field {
    /// This typing session (a new one each time a field takes the focus).
    pub session: [u8; 16],
    pub text: String,
    /// What's being typed for ("Search"): the phone's keyboard title.
    pub title: String,
}

/// `_tiStarted`'s and `_tiStart`'s `_tiD`.
pub fn started(field: &Field) -> Vec<u8> {
    let mut a = Archive::new();
    let text = a.add(Value::String(field.text.clone()));
    let doc = a.object("TIDocumentState", vec![("contextBeforeInput", text)]);
    let state = a.object("RTIDocumentState", vec![("docSt", doc), ("originatedFromSource", Value::Boolean(false))]);
    let title = a.add(Value::String(field.title.clone()));
    let bundle = a.add(Value::String("com.apple.TVSearch".into()));
    let empty = a.add(Value::String(String::new()));
    // TITextInputTraits: the values CompanionGames found a real Apple TV's
    // search field to have (a plain text field, return key "Search").
    let traits = a.object(
        "TITextInputTraits",
        vec![
            ("version", Value::Integer(2.into())),
            ("flags", Value::Integer(1_417_693_830.into())),
            ("auxFlags", Value::Integer(1.into())),
        ],
    );
    let doc_traits = a.object(
        "RTIDocumentTraits",
        vec![
            ("locApp", title),
            ("bId", bundle),
            ("aId", empty),
            ("a2bId", Value::Boolean(true)),
            ("tiTraits", traits),
            ("traitsMask", Value::Integer(576.into())),
        ],
    );
    let session = a.add(Value::Data(field.session.to_vec()));
    a.finish(
        "NSKeyedArchiver",
        vec![("documentState", state), ("documentTraits", doc_traits), ("sessionUUID", session)],
    )
}

/// What the phone's keyboard did.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Edit {
    /// The whole text, replacing the field's (first).
    pub replace: Option<String>,
    /// Characters deleted before the cursor (then).
    pub delete: u32,
    /// Typed at the cursor (last).
    pub insert: String,
}

impl Edit {
    pub fn is_empty(&self) -> bool {
        self.replace.is_none() && self.delete == 0 && self.insert.is_empty()
    }
}

/// Reads `_tiC`'s `_tiD`. None: not an archive of text operations.
pub fn edit(data: &[u8]) -> Option<Edit> {
    let root = Value::from_reader(std::io::Cursor::new(data)).ok()?;
    let root = root.as_dictionary()?;
    let objects = root.get("$objects")?.as_array()?;
    let resolve = |v: &Value| -> Option<Value> {
        match v {
            Value::Uid(u) => objects.get(usize::try_from(u.get()).ok()?).cloned(),
            v => Some(v.clone()),
        }
    };
    let field = |obj: &Value, key: &str| -> Option<Value> { resolve(obj.as_dictionary()?.get(key)?) };
    let string = |v: Value| -> Option<String> {
        match v {
            Value::String(s) if s != "$null" => Some(s),
            // NSMutableString
            Value::Dictionary(d) => d.get("NS.string")?.as_string().map(str::to_owned),
            _ => None,
        }
    };
    let ops = resolve(root.get("$top")?.as_dictionary()?.get("textOperations")?)?;
    ops.as_dictionary()?;
    let output = field(&ops, "keyboardOutput");
    let mut e = Edit {
        replace: field(&ops, "textToAssert").and_then(string),
        delete: output
            .as_ref()
            .and_then(|o| field(o, "deletionCount"))
            .and_then(|v| v.as_unsigned_integer())
            .map_or(0, |n| n.min(10_000) as u32),
        insert: output.as_ref().and_then(|o| field(o, "insertionText")).and_then(string).unwrap_or_default(),
    };
    // Bounded: a phone types, it doesn't send books.
    if e.insert.chars().count() > 4096 {
        e.insert = e.insert.chars().take(4096).collect();
    }
    if let Some(r) = e.replace.as_mut().filter(|r| r.chars().count() > 4096) {
        *r = r.chars().take(4096).collect();
    }
    Some(e)
}

/// The phone's side, for tests and the fake phone: `_tiC`'s `_tiD` for
/// typing `insert` (after deleting `delete`), or replacing the text.
pub fn operations(session: &[u8], replace: Option<&str>, delete: u32, insert: &str) -> Vec<u8> {
    let mut a = Archive::new();
    let mut out = Vec::new();
    if delete > 0 {
        out.push(("deletionCount", Value::Integer(u64::from(delete).into())));
    }
    if !insert.is_empty() {
        out.push(("insertionText", a.add(Value::String(insert.into()))));
    }
    let output = a.object("TIKeyboardOutput", out);
    let mut uuid = Dictionary::new();
    uuid.insert("NS.uuidbytes".into(), Value::Data(session.to_vec()));
    let uuid_class = a.class("NSUUID");
    uuid.insert("$class".into(), uuid_class);
    let uuid = a.add(Value::Dictionary(uuid));
    let mut fields = vec![("keyboardOutput", output), ("targetSessionUUID", uuid)];
    if let Some(r) = replace {
        fields.push(("textToAssert", a.add(Value::String(r.into()))));
    }
    let ops = a.object("RTITextOperations", fields);
    a.finish("RTIKeyedArchiver", vec![("textOperations", ops)])
}

/// Reads `_tiStarted`'s archive (the phone's side): the session and text.
pub fn read_started(data: &[u8]) -> Option<([u8; 16], String)> {
    let root = Value::from_reader(std::io::Cursor::new(data)).ok()?;
    let root = root.as_dictionary()?;
    let objects = root.get("$objects")?.as_array()?;
    let at = |v: &Value| v.as_uid().and_then(|u| objects.get(u.get() as usize));
    let top = root.get("$top")?.as_dictionary()?;
    let session: [u8; 16] = at(top.get("sessionUUID")?)?.as_data()?.try_into().ok()?;
    let state = at(top.get("documentState")?)?.as_dictionary()?;
    let doc = at(state.get("docSt")?)?.as_dictionary()?;
    let text = at(doc.get("contextBeforeInput")?)?.as_string()?.to_owned();
    Some((session, text))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn started_reads_back() {
        let f = Field { session: [7; 16], text: "the wire".into(), title: "Search".into() };
        let bytes = started(&f);
        assert_eq!(&bytes[..8], b"bplist00");
        assert_eq!(read_started(&bytes), Some(([7; 16], "the wire".into())));
    }

    #[test]
    fn edits() {
        let s = [1u8; 16];
        assert_eq!(edit(&operations(&s, None, 0, "héllo")), Some(Edit { insert: "héllo".into(), ..Edit::default() }));
        assert_eq!(edit(&operations(&s, None, 2, "")), Some(Edit { delete: 2, ..Edit::default() }));
        assert_eq!(
            edit(&operations(&s, Some(""), 0, "")),
            Some(Edit { replace: Some(String::new()), ..Edit::default() })
        );
        assert!(edit(&operations(&s, None, 0, "")).unwrap().is_empty());
        assert_eq!(edit(b"bplist00 junk"), None);
        assert_eq!(edit(&started(&Field { session: s, text: String::new(), title: String::new() })), None);
    }

    #[test]
    fn pyatvs_payload_shape() {
        // The shape pyatv's get_rti_input_text_payload writes (objects in its
        // order: the operations, the output, the text, classes, the UUID).
        let mut a = Vec::new();
        let uid = |n| Value::Uid(Uid::new(n));
        let class = |n: &str| {
            let mut d = Dictionary::new();
            d.insert("$classname".into(), Value::String(n.into()));
            d.insert("$classes".into(), Value::Array(vec![Value::String(n.into()), Value::String("NSObject".into())]));
            Value::Dictionary(d)
        };
        let dict =
            |pairs: Vec<(&str, Value)>| Value::Dictionary(pairs.into_iter().map(|(k, v)| (k.to_owned(), v)).collect());
        let objects = vec![
            Value::String("$null".into()),
            dict(vec![("keyboardOutput", uid(2)), ("$class", uid(7)), ("targetSessionUUID", uid(5))]),
            dict(vec![("insertionText", uid(3)), ("$class", uid(4))]),
            Value::String("abc".into()),
            class("TIKeyboardOutput"),
            dict(vec![("NS.uuidbytes", Value::Data(vec![0; 16])), ("$class", uid(6))]),
            class("NSUUID"),
            class("RTITextOperations"),
        ];
        let root = dict(vec![
            ("$version", Value::Integer(100000.into())),
            ("$archiver", Value::String("RTIKeyedArchiver".into())),
            ("$top", dict(vec![("textOperations", uid(1))])),
            ("$objects", Value::Array(objects)),
        ]);
        plist::to_writer_binary(&mut a, &root).unwrap();
        assert_eq!(edit(&a).unwrap().insert, "abc");
    }
}
