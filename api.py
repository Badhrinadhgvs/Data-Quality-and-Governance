from pathlib import Path
import shutil, uuid
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from core import apply_decisions, drift_check, health, infer_schema, match_records, now_iso, profile, read_table
from explainer import generate_explanation, validate_fix

BASE=Path("data"); BASE.mkdir(exist_ok=True); app=FastAPI(title="Data Quality & Governance Copilot",version="1.0.0"); STATE={}; BASELINES={}
class Decision(BaseModel):
    decision:str; reviewer:str="reviewer"; edited_fix:dict|None=None
@app.get("/health")
def alive(): return {"status":"ok"}
@app.post("/datasets")
async def upload(file:UploadFile=File(...),name:str=Form("dataset")):
    if not file.filename.lower().endswith((".csv",".parquet")): raise HTTPException(400,"Only CSV and Parquet are supported")
    did=uuid.uuid4().hex[:10]; path=BASE/f"{did}_{file.filename}"
    with path.open("wb") as dest: shutil.copyfileobj(file.file,dest)
    df=read_table(path); inferred=infer_schema(df); STATE[did]={"id":did,"name":name,"path":str(path),"schema":inferred,"df":df,"audit":[{"timestamp":now_iso(),"event_type":"dataset_uploaded","ref_id":did,"actor":"human","before":{},"after":{"rows":len(df)}}],"decisions":{},"baseline":BASELINES.get(name)}
    return {"dataset_id":did,"name":name,"rows":len(df),"schema":STATE[did]["schema"]}
@app.patch("/datasets/{did}/schema")
def schema(did:str, value:dict):
    if did not in STATE: raise HTTPException(404,"Dataset not found")
    allowed={"id","name","email","phone","date","city","numeric","text"}
    if any(v not in allowed for v in value.values()): raise HTTPException(400,"Unsupported semantic type")
    STATE[did]["schema"]={k:v for k,v in value.items() if k in STATE[did]["df"].columns}; return STATE[did]["schema"]
@app.post("/datasets/{did}/profile")
def run_profile(did:str):
    if did not in STATE: raise HTTPException(404,"Dataset not found")
    s=STATE[did]; s["profile"]=profile(s["df"],s["schema"]); s["health_before"]=health(s["profile"]["dimensions"]); s["issues"]=s["profile"]["issues"]
    s["drift_alerts"]=drift_check(s["profile"],s["baseline"] or s["profile"])
    if s["baseline"] is None: s["baseline"]=s["profile"]; BASELINES[s["name"]]=s["profile"]
    for issue in s["issues"]: s["audit"].append({"timestamp":now_iso(),"event_type":"issue_detected","ref_id":issue["row"],"actor":"system","before":{},"after":issue})
    return {"profile":s["profile"],"health_before":s["health_before"],"drift_alerts":s["drift_alerts"]}
@app.get("/datasets/{did}/issues")
def issues(did:str): return STATE.get(did,{}).get("issues",[])
@app.post("/datasets/{did}/match")
def match(did:str):
    if did not in STATE: raise HTTPException(404,"Dataset not found")
    STATE[did]["matches"]=match_records(STATE[did]["df"],STATE[did]["schema"]); return STATE[did]["matches"]
@app.post("/datasets/{did}/explain")
def explain(did:str):
    if did not in STATE: raise HTTPException(404,"Dataset not found")
    s=STATE[did]; s.setdefault("matches",match_records(s["df"],s["schema"])); s["proposals"]= [generate_explanation(m,s["df"],s["schema"])|m for m in s["matches"]]
    for i,p in enumerate(s["proposals"]): s["audit"].append({"timestamp":now_iso(),"event_type":"proposal_created","ref_id":str(i),"actor":p.get("llm_status","template"),"before":{},"after":p})
    return s["proposals"]
@app.get("/datasets/{did}/proposals")
def proposals(did:str): return STATE.get(did,{}).get("proposals",[])
@app.post("/datasets/{did}/proposals/{pid}/decision")
def decide(did:str,pid:str,decision:Decision):
    if did not in STATE or int(pid)>=len(STATE[did].get("proposals",[])): raise HTTPException(404,"Proposal not found")
    if decision.decision not in {"approve","reject","edit"}: raise HTTPException(400,"Decision must be approve, reject, or edit")
    if decision.edited_fix is not None:
        try: decision.edited_fix=validate_fix(decision.edited_fix,STATE[did]["proposals"][int(pid)],STATE[did]["schema"])
        except ValueError as exc: raise HTTPException(400,str(exc))
    STATE[did]["decisions"][pid]=decision.model_dump(); STATE[did]["audit"].append({"timestamp":now_iso(),"event_type":"decision","ref_id":pid,"actor":decision.reviewer,"before":{},"after":decision.model_dump()}); return STATE[did]["decisions"][pid]
@app.post("/datasets/{did}/apply")
def apply(did:str):
    if did not in STATE: raise HTTPException(404,"Dataset not found")
    s=STATE[did]; out=apply_decisions(s["df"],s.get("proposals",[]),s.get("decisions",{})); path=BASE/f"{did}_cleaned.csv"; out.to_csv(path,index=False); s["cleaned_path"]=str(path); s["health_after"]=health(profile(out,s["schema"])["dimensions"]); s["audit"].append({"timestamp":now_iso(),"event_type":"cleaned_exported","ref_id":did,"actor":"system","before":{"rows":len(s["df"])},"after":{"rows":len(out),"health":s["health_after"]}})
    return {"rows":len(out),"health_before":s.get("health_before"),"health_after":s["health_after"],"download":f"/datasets/{did}/export"}
@app.get("/datasets/{did}/health")
def get_health(did:str): return {"before":STATE.get(did,{}).get("health_before"),"after":STATE.get(did,{}).get("health_after")}
@app.get("/datasets/{did}/audit")
def audit(did:str): return STATE.get(did,{}).get("audit",[])
@app.get("/datasets/{did}/export")
def export(did:str):
    path=STATE.get(did,{}).get("cleaned_path")
    if not path: raise HTTPException(404,"Apply approved decisions first")
    return FileResponse(path,filename=Path(path).name,media_type="text/csv")
