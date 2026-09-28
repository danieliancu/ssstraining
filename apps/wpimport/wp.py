"""Read-only access to the WordPress database for the import commands."""
from collections import defaultdict
from datetime import datetime, timezone as dt_tz

import phpserialize
from django.conf import settings
from django.db import connections


def unserialize(value):
    """Decode a PHP-serialized value; plain strings pass through."""
    if not isinstance(value, str) or not value or value[:2] not in ("a:", "s:", "i:", "b:", "d:", "O:", "N;"):
        return value
    try:
        data = phpserialize.loads(value.encode("utf-8"), decode_strings=True, object_hook=phpserialize.phpobject)
    except Exception:
        return value
    return _to_python(data)


def _to_python(data):
    if isinstance(data, dict):
        keys = list(data.keys())
        if keys == list(range(len(keys))):
            return [_to_python(v) for v in data.values()]
        return {k: _to_python(v) for k, v in data.items()}
    if isinstance(data, phpserialize.phpobject):
        return _to_python(data._asdict())
    return data


def gmt_datetime(value):
    if not value or str(value).startswith("0000"):
        return None
    if isinstance(value, str):
        value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return value.replace(tzinfo=dt_tz.utc)


class WordPress:
    def __init__(self, alias="wordpress"):
        self.conn = connections[alias]
        self.prefix = settings.WP_TABLE_PREFIX
        self._acf_fields = None

    def t(self, name):
        return f"`{self.prefix}{name}`"

    def query(self, sql, params=None):
        sql = sql.replace("{p}", self.prefix)
        with self.conn.cursor() as cur:
            cur.execute(sql, params or [])
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def scalar(self, sql, params=None):
        rows = self.query(sql, params)
        return next(iter(rows[0].values())) if rows else None

    # --- options -----------------------------------------------------------------
    def option(self, name, default=None):
        value = self.scalar("SELECT option_value FROM {p}options WHERE option_name=%s", [name])
        return default if value is None else unserialize(value)

    def options_like(self, pattern):
        rows = self.query("SELECT option_name, option_value FROM {p}options WHERE option_name LIKE %s", [pattern])
        return {r["option_name"]: r["option_value"] for r in rows}

    # --- posts ---------------------------------------------------------------------
    def posts(self, post_type, statuses=("publish",), ids=None):
        sql = "SELECT * FROM {p}posts WHERE post_type=%s AND post_status IN (" + ",".join(["%s"] * len(statuses)) + ")"
        params = [post_type, *statuses]
        if ids:
            sql += " AND ID IN (" + ",".join(["%s"] * len(ids)) + ")"
            params += list(ids)
        return self.query(sql + " ORDER BY ID", params)

    def post(self, post_id):
        rows = self.query("SELECT * FROM {p}posts WHERE ID=%s", [post_id])
        return rows[0] if rows else None

    def postmeta(self, post_ids):
        if not post_ids:
            return {}
        out = defaultdict(dict)
        ids = list(post_ids)
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            rows = self.query(
                "SELECT post_id, meta_key, meta_value FROM {p}postmeta WHERE post_id IN (" + ",".join(["%s"] * len(chunk)) + ")",
                chunk)
            for r in rows:
                out[r["post_id"]][r["meta_key"]] = r["meta_value"]
        return out

    # --- terms ---------------------------------------------------------------------
    def terms(self, taxonomy):
        return self.query(
            "SELECT t.term_id, t.name, t.slug, tt.term_taxonomy_id, tt.description, tt.parent, tt.count "
            "FROM {p}terms t JOIN {p}term_taxonomy tt ON tt.term_id=t.term_id WHERE tt.taxonomy=%s ORDER BY tt.parent, t.term_id",
            [taxonomy])

    def termmeta(self, term_ids):
        out = defaultdict(dict)
        if not term_ids:
            return out
        ids = list(term_ids)
        rows = self.query(
            "SELECT term_id, meta_key, meta_value FROM {p}termmeta WHERE term_id IN (" + ",".join(["%s"] * len(ids)) + ")", ids)
        for r in rows:
            out[r["term_id"]][r["meta_key"]] = r["meta_value"]
        return out

    def object_terms(self, taxonomy, object_ids=None):
        """{object_id: [term_id, ...]} for a taxonomy."""
        sql = ("SELECT tr.object_id, tt.term_id FROM {p}term_relationships tr "
               "JOIN {p}term_taxonomy tt ON tt.term_taxonomy_id=tr.term_taxonomy_id WHERE tt.taxonomy=%s")
        rows = self.query(sql, [taxonomy])
        out = defaultdict(list)
        wanted = set(object_ids) if object_ids is not None else None
        for r in rows:
            if wanted is None or r["object_id"] in wanted:
                out[r["object_id"]].append(r["term_id"])
        return out

    # --- ACF -----------------------------------------------------------------------
    @property
    def acf_fields(self):
        """{field_key: {"name", "type", "parent_key", "sub_fields": [...]}} from acf-field posts."""
        if self._acf_fields is None:
            rows = self.query(
                "SELECT ID, post_name, post_excerpt, post_content, post_parent, menu_order FROM {p}posts "
                "WHERE post_type IN ('acf-field', 'acf-field-group') ORDER BY menu_order")
            by_id = {r["ID"]: r for r in rows}
            fields = {}
            for r in rows:
                if not r["post_name"].startswith("field_"):
                    continue
                conf = unserialize(r["post_content"]) or {}
                parent = by_id.get(r["post_parent"])
                fields[r["post_name"]] = {
                    "name": r["post_excerpt"],
                    "type": conf.get("type", "text") if isinstance(conf, dict) else "text",
                    "parent_key": parent["post_name"] if parent else "",
                    "sub_fields": [],
                }
            for key, f in fields.items():
                if f["parent_key"] in fields:
                    fields[f["parent_key"]]["sub_fields"].append(key)
            self._acf_fields = fields
        return self._acf_fields

    def acf_values(self, meta, prefix=""):
        """Rebuild ACF values from a flat meta dict (postmeta, termmeta or options_*)."""
        fields = self.acf_fields
        values = {}
        for meta_key, field_key in meta.items():
            if not meta_key.startswith("_" + prefix) or not isinstance(field_key, str) or not field_key.startswith("field_"):
                continue
            name = meta_key[1 + len(prefix):]
            field = fields.get(field_key)
            if field and field["parent_key"] in fields:
                continue  # sub-field of a repeater; handled by its parent
            if not field and "_" in name and any(name.startswith(f"{n}_") for n in values):
                continue
            values[name] = self._acf_value(meta, prefix + name, field_key)
        return values

    def _acf_value(self, meta, key, field_key):
        field = self.acf_fields.get(field_key)
        raw = meta.get(key)
        if not field:
            return unserialize(raw)
        if field["type"] in ("repeater", "flexible_content"):
            try:
                count = int(raw or 0)
            except (TypeError, ValueError):
                count = 0
            rows = []
            for i in range(count):
                row = {}
                for sub_key in field["sub_fields"]:
                    sub = self.acf_fields[sub_key]
                    row[sub["name"]] = self._acf_value(meta, f"{key}_{i}_{sub['name']}", sub_key)
                rows.append(row)
            return rows
        if field["type"] == "group":
            return {self.acf_fields[s]["name"]: self._acf_value(meta, f"{key}_{self.acf_fields[s]['name']}", s)
                    for s in field["sub_fields"]}
        if field["type"] == "true_false":
            return raw == "1"
        return unserialize(raw)
