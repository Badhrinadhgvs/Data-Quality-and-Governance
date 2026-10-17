import pandas as pd
from core import health,infer_schema,match_records,normalize_date,normalize_phone,profile
def demo(): return pd.DataFrame([{"id":"C001","name":"Rajesh Kumar","dob":"1985-03-12","email":"rajesh.k@gmail.com","phone":"9876543210","city":"Hyderabad"},{"id":"C002","name":"Rajesh Kumaar","dob":"12/03/1985","email":"rajesh.k@gmail.com","phone":"+91 98765 43210","city":"Hderabad"},{"id":"C003","name":"राजेश कुमार","dob":"1985-03-12","email":"","phone":"9876543210","city":"हैदराबाद"},{"id":"C004","name":"Priya Sharma","dob":"1990-07-01","email":"priya@xyz","phone":"9123456780","city":"Chennai"},{"id":"C005","name":"Priya Sharma","dob":"1990-07-01","email":"priya@xyz.com","phone":"9123456780","city":"Chennai"},{"id":"C006","name":"Anil Reddy","dob":"1978-11-30","email":"anil@ex.com","phone":"99999","city":"Nellore"}])
def test_normalizers(): assert normalize_phone("+91 98765 43210")=="9876543210" and normalize_date("12/03/1985")[0]=="1985-03-12"
def test_profile():
    d=demo(); p=profile(d,infer_schema(d)); assert any(x["type"]=="invalid" for x in p["issues"]) and 0<=health(p["dimensions"])<=100
def test_matching(): assert any({m["record_a"],m["record_b"]}=={"0","1"} for m in match_records(demo(),infer_schema(demo())))
