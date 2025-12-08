import asyncio
from typing import List, Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import json
import random

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="static")

# --- GAME CONFIGURATION ---
ROUNDS_CONFIG = {
    "consoles": {
        "id": "consoles",
        "question": "Which platform is superior?",
        "options": ["Xbox", "PlayStation"],
        "colors": ["#107C10", "#003791"],
        "icons": ["fa-brands fa-xbox", "fa-brands fa-playstation"]
    },
    "chicken_egg": {
        "id": "chicken_egg",
        "question": "Which came first?",
        "options": ["Chicken", "Egg"],
        "colors": ["#D35400", "#F1C40F"],
        "icons": ["fa-solid fa-crow", "fa-solid fa-egg"]
    },
    "simulation": {
        "id": "simulation",
        "question": "Are we living in a simulation?",
        "options": ["Yes", "No"],
        "colors": ["#2ecc71", "#e74c3c"],
        "icons": ["fa-solid fa-microchip", "fa-solid fa-ban"]
    },
    "daylight": {
        "id": "daylight",
        "question": "Should we abolish Daylight Savings?",
        "options": ["Yes", "No"],
        "colors": ["#34495e", "#f39c12"],
        "icons": ["fa-solid fa-thumbs-up", "fa-solid fa-clock"]
    }
}

class GameManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.admin_connection: Optional[WebSocket] = None
        # Seats: { seat_id: { "ws": WebSocket, "client_id": str, "name": str, "total_score": 0, "round_score": 0, "vote_idx": None } }
        self.seats: Dict[int, dict] = {} 
        self.game_phase = "LOGIN"
        
        self.current_round_id = "consoles"
        self.vote_counts = [0, 0] 
        self.global_map = [] 

    async def connect_player(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        
        # Send initial config data
        await websocket.send_text(json.dumps({
            "type": "seat_map_update", 
            "taken_seats": list(self.seats.keys())
        }))
        await websocket.send_text(json.dumps({
            "type": "round_setup",
            "config": ROUNDS_CONFIG[self.current_round_id]
        }))

    async def connect_admin(self, websocket: WebSocket):
        await websocket.accept()
        self.admin_connection = websocket
        await self.broadcast_admin_update()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            
            # Find which seat this socket belonged to
            for seat_id, data in self.seats.items():
                if data.get('ws') == websocket:
                    # Mark the connection as None, but DO NOT delete the seat.
                    # This preserves the seat for reconnection/refresh.
                    data['ws'] = None
                    break
        
        if websocket == self.admin_connection:
            self.admin_connection = None
            
        # Notify admin (to update online status visuals)
        asyncio.create_task(self.broadcast_admin_update())

    async def broadcast_seat_map(self):
        msg = {
            "type": "seat_map_update", 
            "taken_seats": list(self.seats.keys())
        }
        json_msg = json.dumps(msg)
        for connection in self.active_connections:
            try:
                await connection.send_text(json_msg)
            except:
                pass
        await self.broadcast_admin_update()

    async def broadcast_to_players(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except:
                pass

    async def broadcast_admin_update(self):
        if self.admin_connection:
            players_list = []
            for seat_id, data in self.seats.items():
                players_list.append({
                    "seat": seat_id,
                    "name": data["name"],
                    "total_score": data.get("total_score", 0),
                    "round_score": data.get("round_score", 0),
                    "online": data.get("ws") is not None # Status flag
                })
            
            players_list.sort(key=lambda x: x["total_score"], reverse=True)

            opts = ROUNDS_CONFIG[self.current_round_id]["options"]
            votes_dict = {opts[0]: self.vote_counts[0], opts[1]: self.vote_counts[1]}

            data = {
                "type": "admin_update",
                "phase": self.game_phase,
                "round_id": self.current_round_id,
                "player_count": len(self.seats),
                "players": players_list,
                "votes": votes_dict,
                "round_info": ROUNDS_CONFIG[self.current_round_id]
            }
            try:
                await self.admin_connection.send_text(json.dumps(data))
            except:
                pass

    # --- ACTIONS ---

    async def handle_identify(self, websocket: WebSocket, client_id: str):
        """Checks if a client_id already has a seat and reconnects them."""
        for seat_id, data in self.seats.items():
            if data.get("client_id") == client_id:
                # RECONNECTION LOGIC
                data["ws"] = websocket # Update to new socket
                
                # Restore session for the user
                await websocket.send_text(json.dumps({
                    "type": "restore_session",
                    "seatId": seat_id,
                    "name": data["name"],
                    "phase": self.game_phase,
                    "map_data": self.global_map if self.global_map else None,
                    "round_info": ROUNDS_CONFIG[self.current_round_id]
                }))
                
                await self.broadcast_admin_update()
                return

    async def handle_seat_claim(self, websocket: WebSocket, seat_id: int, client_id: str):
        if seat_id in self.seats:
            # Check if it's the same person (edge case)
            if self.seats[seat_id].get("client_id") == client_id:
                 self.seats[seat_id]["ws"] = websocket
                 return
            
            await websocket.send_text(json.dumps({"type": "error", "message": "Seat Already Taken"}))
            return
        
        # Remove old seat if this specific client ID had one
        for s_id, data in list(self.seats.items()):
            if data.get('client_id') == client_id:
                del self.seats[s_id]
                break

        self.seats[seat_id] = {
            "ws": websocket, 
            "client_id": client_id,
            "name": f"Desk #{seat_id + 1}",
            "total_score": 0,
            "round_score": 0,
            "vote_idx": None
        }
        
        await websocket.send_text(json.dumps({
            "type": "login_success", 
            "seatId": seat_id,
            "name": f"Desk #{seat_id + 1}"
        }))
        await self.broadcast_seat_map()

    async def handle_vote(self, seat_id: int, party_name: str):
        if seat_id not in self.seats:
            return

        options = ROUNDS_CONFIG[self.current_round_id]["options"]
        if party_name == options[0]:
            idx = 0
        elif party_name == options[1]:
            idx = 1
        else:
            return

        self.seats[seat_id]["vote_idx"] = idx
        
        # Recalculate global votes
        self.vote_counts = [0, 0]
        for s in self.seats.values():
            v = s.get("vote_idx")
            if v is not None:
                self.vote_counts[v] += 1
                
        await self.broadcast_admin_update()

    async def handle_score_submission(self, seat_id: int, score: int):
        if seat_id in self.seats:
            self.seats[seat_id]["round_score"] = score
            self.seats[seat_id]["total_score"] += score
        await self.broadcast_admin_update()

    def generate_global_map(self):
        new_map = []
        for i in range(30):
            if i in self.seats and self.seats[i]["vote_idx"] is not None:
                new_map.append(self.seats[i]["vote_idx"])
            else:
                new_map.append(0 if random.random() > 0.5 else 1)
        return new_map

    async def set_round(self, round_id: str):
        if round_id in ROUNDS_CONFIG:
            self.current_round_id = round_id
            self.vote_counts = [0, 0]
            for s in self.seats:
                self.seats[s]["vote_idx"] = None
            
            await self.broadcast_to_players({
                "type": "round_setup",
                "config": ROUNDS_CONFIG[round_id]
            })
            await self.broadcast_admin_update()

    async def change_phase(self, new_phase: str):
        self.game_phase = new_phase
        msg = {"type": "phase_change", "phase": new_phase}

        if new_phase == "LOGIN":
            self.vote_counts = [0, 0]
            for s in self.seats:
                self.seats[s]["vote_idx"] = None
                self.seats[s]["round_score"] = 0
            
        elif new_phase == "GAME":
            self.global_map = self.generate_global_map()
            msg["map_data"] = self.global_map

        elif new_phase == "RESULTS":
            sorted_scores = sorted(self.seats.values(), key=lambda x: x["total_score"], reverse=True)
            leaderboard = [{
                "name": p["name"], 
                "score": p["total_score"], 
                "round": p["round_score"]
            } for p in sorted_scores]
            msg["leaderboard"] = leaderboard

        await self.broadcast_to_players(msg)
        await self.broadcast_admin_update()

    async def handle_reset_game(self):
        """Resets the game state to its initial configuration."""
        self.seats = {}
        self.game_phase = "LOGIN"
        self.current_round_id = "consoles"
        self.vote_counts = [0, 0]
        self.global_map = []

        # Send Reset Signal to everyone
        await self.broadcast_to_players({"type": "game_reset"})
        await self.broadcast_admin_update()


manager = GameManager()

@app.get("/", response_class=HTMLResponse)
async def get_game(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def get_admin(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request, "rounds": ROUNDS_CONFIG})

@app.get("/logo" , response_class=HTMLResponse)
async def get_logo(request: Request):
    return FileResponse("static/images/logo.png")

@app.websocket("/ws/player")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect_player(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            if msg["type"] == "identify":
                await manager.handle_identify(websocket, msg["clientId"])

            elif msg["type"] == "claim_seat":
                await manager.handle_seat_claim(websocket, msg["seatId"], msg["clientId"])

            elif msg["type"] == "vote":
                for s_id, s_data in manager.seats.items():
                    if s_data['ws'] == websocket:
                        await manager.handle_vote(s_id, msg["party"])
                        break

            elif msg["type"] == "finish_round":
                if "seatId" in msg and "score" in msg:
                    await manager.handle_score_submission(msg["seatId"], msg["score"])

    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.websocket("/ws/admin")
async def websocket_admin(websocket: WebSocket):
    await manager.connect_admin(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            if msg["type"] == "set_phase":
                await manager.change_phase(msg["phase"])
            elif msg["type"] == "set_round":
                await manager.set_round(msg["round_id"])
            elif msg["type"] == "reset_game":
                await manager.handle_reset_game()
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)