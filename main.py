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
# Converted to a list of keys to preserve order for the flow
ROUND_KEYS = ["consoles", "chicken_egg", "simulation", "daylight"]

ROUNDS_CONFIG = {
    "consoles": {
        "id": "consoles", "question": "Which platform is superior?",
        "options": ["Xbox", "PlayStation"], "colors": ["#107C10", "#003791"],
        "icons": ["fa-brands fa-xbox", "fa-brands fa-playstation"]
    },
    "chicken_egg": {
        "id": "chicken_egg", "question": "Which came first?",
        "options": ["Chicken", "Egg"], "colors": ["#D35400", "#F1C40F"],
        "icons": ["fa-solid fa-crow", "fa-solid fa-egg"]
    },
    "simulation": {
        "id": "simulation", "question": "Are we living in a simulation?",
        "options": ["Yes", "No"], "colors": ["#2ecc71", "#e74c3c"],
        "icons": ["fa-solid fa-microchip", "fa-solid fa-ban"]
    },
    "daylight": {
        "id": "daylight", "question": "Should we abolish Daylight Savings?",
        "options": ["Yes", "No (Keep it)"], "colors": ["#34495e", "#f39c12"],
        "icons": ["fa-solid fa-thumbs-up", "fa-solid fa-clock"]
    },
    "mobile_os": {
        "id": "mobile_os", "question": "iOS or Android?",
        "options": ["Apple", "Android"], "colors": ["#A2AAAD", "#3DDC84"],
        "icons": ["fa-brands fa-apple", "fa-brands fa-android"]
    },
    "morning_night": {
        "id": "morning_night", "question": "When are you most productive?",
        "options": ["Early Bird", "Night Owl"], "colors": ["#f39c12", "#2c3e50"],
        "icons": ["fa-solid fa-sun", "fa-solid fa-moon"]
    },
    "gif_pronunciation": {
        "id": "gif_pronunciation", "question": "How do you pronounce GIF?",
        "options": ["Hard G (Gift)", "Soft G (Jif)"], "colors": ["#1abc9c", "#9b59b6"],
        "icons": ["fa-solid fa-g", "fa-solid fa-jar"]
    },
    "toilet_paper": {
        "id": "toilet_paper", "question": "Toilet paper orientation?",
        "options": ["Over", "Under"], "colors": ["#34495e", "#bdc3c7"],
        "icons": ["fa-solid fa-arrow-up", "fa-solid fa-arrow-down"]
    }
}

class GameManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.admin_connection: Optional[WebSocket] = None
        # Seats: { seat_id: { "ws": WebSocket, "client_id": str, "name": str, "total_score": 0, "round_score": 0, "vote_idx": None } }
        self.seats: Dict[int, dict] = {} 
        self.game_phase = "LOGIN"
        
        self.current_round_index = 0
        self.current_round_id = ROUND_KEYS[0]
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
            # We do NOT remove the seat data on disconnect to allow reconnection
            # We just set the WS to None
            for seat_id, data in self.seats.items():
                if data.get('ws') == websocket:
                    data['ws'] = None
                    break
        
        if websocket == self.admin_connection:
            self.admin_connection = None
            
        asyncio.create_task(self.broadcast_admin_update())

    async def broadcast_seat_map(self):
        msg = { "type": "seat_map_update", "taken_seats": list(self.seats.keys()) }
        json_msg = json.dumps(msg)
        for connection in self.active_connections:
            try: await connection.send_text(json_msg)
            except: pass
        await self.broadcast_admin_update()

    async def broadcast_to_players(self, message: dict):
        for connection in self.active_connections:
            try: await connection.send_text(json.dumps(message))
            except: pass

    async def broadcast_admin_update(self):
        if self.admin_connection:
            players_list = []
            votes_cast_count = 0
            
            for seat_id, data in self.seats.items():
                has_voted = data.get("vote_idx") is not None
                if has_voted: votes_cast_count += 1
                
                players_list.append({
                    "seat": seat_id,
                    "name": data["name"],
                    "total_score": data.get("total_score", 0),
                    "round_score": data.get("round_score", 0),
                    "online": data.get("ws") is not None,
                    "has_voted": has_voted
                })
            
            players_list.sort(key=lambda x: x["total_score"], reverse=True)

            opts = ROUNDS_CONFIG[self.current_round_id]["options"]
            votes_dict = {opts[0]: self.vote_counts[0], opts[1]: self.vote_counts[1]}

            # Determine if we can proceed
            can_progress = False
            if self.game_phase == "LOGIN":
                can_progress = len(self.seats) > 0
            elif self.game_phase == "VOTE":
                # Only allow progress if everyone online has voted, or at least 1 person if generous
                can_progress = (votes_cast_count > 0 and votes_cast_count == len([s for s in self.seats.values() if s['ws'] is not None]))
            elif self.game_phase == "GAME":
                can_progress = True # Admin can end game anytime
            elif self.game_phase == "RESULTS":
                can_progress = True # Logic handled by timer usually

            data = {
                "type": "admin_update",
                "phase": self.game_phase,
                "round_id": self.current_round_id,
                "round_index": self.current_round_index,
                "total_rounds": len(ROUND_KEYS),
                "player_count": len(self.seats),
                "players": players_list,
                "votes": votes_dict,
                "can_progress": can_progress,
                "round_info": ROUNDS_CONFIG[self.current_round_id]
            }
            try: await self.admin_connection.send_text(json.dumps(data))
            except: pass

    # --- ACTIONS ---

    async def kick_player(self, seat_id: int):
        if seat_id in self.seats:
            data = self.seats[seat_id]
            ws = data.get("ws")
            
            # Notify player they were kicked
            if ws:
                print(f"Attempting to kick player at seat {seat_id}")
                try:
                    await ws.send_text(json.dumps({"type": "kicked_by_admin"}))
                    print(f"Sent kick message to player at seat {seat_id}")
                    # Optional: Close the socket or let client handle it
                except Exception as e:
                    print(f"Error sending kick message to player at seat {seat_id}: {e}")
            
            del self.seats[seat_id]
            await self.broadcast_seat_map()

    async def handle_identify(self, websocket: WebSocket, client_id: str):
        for seat_id, data in self.seats.items():
            if data.get("client_id") == client_id:
                data["ws"] = websocket
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
            if self.seats[seat_id].get("client_id") == client_id:
                 self.seats[seat_id]["ws"] = websocket
                 return
            await websocket.send_text(json.dumps({"type": "error", "message": "Seat Already Taken"}))
            return
        
        # Ensure one seat per client
        for s_id, data in list(self.seats.items()):
            if data.get('client_id') == client_id:
                del self.seats[s_id]
                break

        self.seats[seat_id] = {
            "ws": websocket, "client_id": client_id,
            "name": f"Desk #{seat_id + 1}",
            "total_score": 0, "round_score": 0, "vote_idx": None
        }
        
        await websocket.send_text(json.dumps({
            "type": "login_success", "seatId": seat_id, "name": f"Desk #{seat_id + 1}"
        }))
        await self.broadcast_seat_map()

    async def handle_vote(self, seat_id: int, party_name: str):
        if seat_id not in self.seats: return

        options = ROUNDS_CONFIG[self.current_round_id]["options"]
        if party_name == options[0]: idx = 0
        elif party_name == options[1]: idx = 1
        else: return

        self.seats[seat_id]["vote_idx"] = idx
        
        # Recalculate global votes
        self.vote_counts = [0, 0]
        for s in self.seats.values():
            v = s.get("vote_idx")
            if v is not None: self.vote_counts[v] += 1
                
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

    async def advance_round(self):
        # Move to next round
        if self.current_round_index < len(ROUND_KEYS) - 1:
            self.current_round_index += 1
            self.current_round_id = ROUND_KEYS[self.current_round_index]
            
            # Reset round data
            self.vote_counts = [0, 0]
            for s in self.seats:
                self.seats[s]["vote_idx"] = None
                self.seats[s]["round_score"] = 0
            
            # Broadcast new config
            await self.broadcast_to_players({
                "type": "round_setup",
                "config": ROUNDS_CONFIG[self.current_round_id]
            })
            
            # Set phase to VOTE
            await self.change_phase("VOTE")
        else:
            # End of Game
             await self.broadcast_to_players({"type": "game_over"})
             await self.change_phase("RESULTS") # Keep on results but maybe show winner

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
        self.seats = {}
        self.game_phase = "LOGIN"
        self.current_round_index = 0
        self.current_round_id = ROUND_KEYS[0]
        self.vote_counts = [0, 0]
        self.global_map = []
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
            
            if msg["type"] == "action_next":
                # State Machine for the Single Button
                if manager.game_phase == "LOGIN":
                    await manager.change_phase("VOTE")
                elif manager.game_phase == "VOTE":
                    await manager.change_phase("GAME")
                elif manager.game_phase == "GAME":
                    await manager.change_phase("RESULTS")
                elif manager.game_phase == "RESULTS":
                    await manager.advance_round()

            elif msg["type"] == "kick_player":
                await manager.kick_player(msg["seat_id"])
            elif msg["type"] == "reset_game":
                await manager.handle_reset_game()
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)