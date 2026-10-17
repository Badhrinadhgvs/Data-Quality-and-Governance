"""Deterministic, human-in-the-loop data quality engine."""
from __future__ import annotations
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
from rapidfuzz.fuzz import ratio
from unidecode import unidecode

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

def now_iso(): return datetime.now(timezone.utc).isoformat()
def clean_text(v): return re.sub(r"\s+", " ", unidecode(str(v or "")).strip().lower())
def normalize_phone(v):
    d = re.sub(r"\D", "", str(v or "")); return d[-10:] if len(d) >= 10 else d
def normalize_date(v):
    raw = str(v or "").strip(); parts = re.split(r"[-/]", raw)
    if not raw or raw.lower() in {"nan", "none", "nat"}: return None, False
    try:
        ambiguous = len(parts) == 3 and len(parts[0]) <= 2 and len(parts[1]) <= 2 and int(parts[0]) <= 12 and int(parts[1]) <= 12
        dt = pd.to_datetime(raw, dayfirst=len(parts[0]) != 4, errors="raise")
        return dt.strftime("%Y-%m-%d"), ambiguous
    except (ValueError, TypeError, OverflowError): return None, False

def infer_schema(df):
    out = {}
    for col in df.columns:
        n = str(col).lower().replace("_", " "); s = df[col].dropna().astype(str).head(100)
        if "email" in n: kind = "email"
        elif re.search(r"phone|mobile|telephone|contact", n): kind = "phone"
        elif re.search(r"dob|birth|date|created|updated", n): kind = "date"
        elif re.search(r"(^| )(id|key)$|identifier", n): kind = "id"
        elif "name" in n: kind = "name"
        elif "city" in n or "town" in n: kind = "city"
        elif pd.api.types.is_numeric_dtype(df[col]): kind = "numeric"
        elif len(s) and s.map(lambda x: bool(EMAIL_RE.match(x))).mean() >= .8: kind = "email"
        else: kind = "text"
        out[str(col)] = kind
    return out

def profile(df, schema):
    cols, issues = [], []
    for col in df.columns:
        kind = schema.get(str(col), "text"); s = df[col]; missing = s.isna() | s.astype(str).str.strip().isin({"", "nan", "None"}); valid = ~missing
        if kind == "email": valid &= s.astype(str).map(lambda x: bool(EMAIL_RE.match(x)))
        elif kind == "phone": valid &= s.astype(str).map(lambda x: len(normalize_phone(x)) == 10)
        elif kind == "date": valid &= s.astype(str).map(lambda x: normalize_date(x)[0] is not None)
        cols.append({"column": str(col), "type": kind, "null_pct": round(float(missing.mean()*100), 2), "valid_pct": round(float(valid.mean()*100), 2), "unique_pct": round(float(s[~missing].nunique()/max(1,(~missing).sum())*100), 2), "format_variants": int(s[~missing].astype(str).nunique())})
        for i in df.index[missing]: issues.append({"type":"missing","column":str(col),"row":str(i),"value":None,"severity":"medium","rule":"non-null expected"})
        for i in df.index[~valid & ~missing]: issues.append({"type":"invalid","column":str(col),"row":str(i),"value":str(df.at[i,col]),"severity":"high","rule":f"valid {kind} value"})
        if kind == "date":
            for i, v in s.items():
                parsed, amb = normalize_date(v)
                if parsed and amb: issues.append({"type":"ambiguous_date","column":str(col),"row":str(i),"value":str(v),"severity":"medium","rule":"ambiguous day/month; review required"})
    dup = df.duplicated(keep=False)
    for i in df.index[dup]: issues.append({"type":"exact_duplicate","column":None,"row":str(i),"value":None,"severity":"high","rule":"exact duplicate row"})
    dims = {"completeness": round(float(np.mean([100-c["null_pct"] for c in cols])) if cols else 100,2), "validity": round(float(np.mean([c["valid_pct"] for c in cols])) if cols else 100,2), "uniqueness": round(100-float(dup.mean()*100) if len(df) else 100,2), "consistency": round(float(np.mean([100 if c["format_variants"] <= max(1,int(len(df)*.4)) else 80 for c in cols])) if cols else 100,2)}
    return {"columns":cols,"issues":issues,"dimensions":dims,"rows":len(df),"created_at":now_iso()}

def standardize(df, schema):
    out, changes = df.copy(), []
    for col, kind in schema.items():
        if col not in out: continue
        for i, v in out[col].items():
            new, amb = v, False
            if kind == "phone": new = normalize_phone(v)
            elif kind in {"name","city","text"}: new = clean_text(v)
            elif kind == "date": new, amb = normalize_date(v)
            if not (pd.isna(v) and pd.isna(new)) and str(v) != str(new): changes.append({"row":str(i),"column":col,"before":v,"after":new,"ambiguous":amb})
            out.at[i,col] = new
    return out, changes

def _phonetic(v):
    return " ".join(w[:1]+re.sub(r"[aeiou]", "", w[1:])[:5] for w in re.findall(r"[a-z]+", clean_text(v)))

def match_records(df, schema):
    work, _ = standardize(df, schema); name=next((c for c,t in schema.items() if t=="name"),None); dob=next((c for c,t in schema.items() if t=="date"),None); phone=next((c for c,t in schema.items() if t=="phone"),None); email=next((c for c,t in schema.items() if t=="email"),None); city=next((c for c,t in schema.items() if t=="city"),None)
    blocks = defaultdict(set)
    for i,r in work.iterrows():
        for k in (["p:"+normalize_phone(r.get(phone))] if phone and normalize_phone(r.get(phone)) else []) + (["d:"+str(r.get(dob))] if dob and r.get(dob) else []) + (["n:"+_phonetic(r.get(name))] if name and r.get(name) else []): blocks[k].add(i)
    pairs = {(a,b) for mem in blocks.values() for pos,a in enumerate(sorted(mem)) for b in sorted(mem)[pos+1:]}; results=[]
    for a,b in sorted(pairs):
        ra,rb=work.loc[a],work.loc[b]; scores={}
        if name: scores["name"]=ratio(str(ra.get(name,"")),str(rb.get(name,"")))/100
        if dob: scores["dob"]=float(bool(ra.get(dob)) and ra.get(dob)==rb.get(dob))
        if phone: scores["phone"]=float(bool(normalize_phone(ra.get(phone))) and normalize_phone(ra.get(phone))==normalize_phone(rb.get(phone)))
        if email: scores["email"]=float(bool(ra.get(email)) and clean_text(ra.get(email))==clean_text(rb.get(email)))
        if city: scores["city"]=ratio(clean_text(ra.get(city)),clean_text(rb.get(city)))/100
        weights={"name":.30,"dob":.25,"phone":.25,"email":.15,"city":.05}; active={k:v for k,v in weights.items() if k in scores and (k!="email" or scores[k] or (ra.get(email) and rb.get(email)))}; score=sum(active[k]*scores[k] for k in active)/sum(active.values()) if active else 0
        if score >= .75: results.append({"record_a":str(a),"record_b":str(b),"field_scores":scores,"score":round(score,4),"band":"High" if score>=.95 else "Review"})
    return results

def health(d): return round(.25*d.get("completeness",100)+.25*d.get("validity",100)+.20*d.get("uniqueness",100)+.20*d.get("consistency",100)+10,2)
def proposal_for_match(m, df):
    a,b=m["record_a"],m["record_b"]; survivor=a if df.loc[int(a)].notna().sum()>=df.loc[int(b)].notna().sum() else b
    return {"summary":f"Records {a} and {b} appear to describe the same entity.","reasoning":f"Deterministic matching found a {m['band'].lower()} confidence match ({m['score']:.2f}). Evidence: "+", ".join(f"{k}={v:.2f}" for k,v in m["field_scores"].items())+".","proposed_fix":{"action":"merge_records","survivor":survivor,"field_updates":{}},"confidence":m["score"],"risk":"low" if m["score"]>=.95 else "medium","llm_status":"template_fallback"}
def apply_decisions(df, proposals, decisions):
    out=df.copy()
    for pid,p in enumerate(proposals):
        d=decisions.get(str(pid),{});
        if d.get("decision")!="approve": continue
        fix=d.get("edited_fix") or p["proposed_fix"]
        if fix.get("action")=="merge_records":
            s=str(fix.get("survivor")); other=[x for x in [p.get("record_a"),p.get("record_b")] if x is not None and str(x)!=s]
            for o in other:
                if int(o) in out.index and int(s) in out.index:
                    for c in out.columns:
                        if pd.isna(out.at[int(s),c]) or str(out.at[int(s),c]).strip()=="": out.at[int(s),c]=out.at[int(o),c]
                    out=out.drop(index=int(o))
        for c,v in fix.get("field_updates",{}).items():
            if c in out.columns and int(fix.get("survivor",-1)) in out.index: out.at[int(fix["survivor"]),c]=v
    return out.reset_index(drop=True)
def read_table(path): return pd.read_parquet(path) if Path(path).suffix.lower()==".parquet" else pd.read_csv(path)

def drift_check(current, baseline, null_threshold=5.0, category_threshold=10.0):
    """Compare two profiles and return explainable alerts."""
    alerts = []
    old = {x["column"]: x for x in baseline.get("columns", [])}
    for item in current.get("columns", []):
        previous = old.get(item["column"])
        if not previous: continue
        delta = item["null_pct"] - previous["null_pct"]
        if abs(delta) >= null_threshold:
            alerts.append({"type": "null_rate_drift", "column": item["column"], "change_pp": round(delta, 2), "threshold": null_threshold})
        old_variants = max(1, previous.get("format_variants", 1)); new_variants = max(1, item.get("format_variants", 1))
        if abs(new_variants - old_variants) / old_variants * 100 >= category_threshold:
            alerts.append({"type": "format_distribution_drift", "column": item["column"], "previous_variants": old_variants, "current_variants": new_variants, "threshold": category_threshold})
    return alerts
