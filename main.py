from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Hello, FastAPI with Docker!"} 

@app.get("/create-offer")
def handle_create_offer():
    return {"message": "Create offer"}