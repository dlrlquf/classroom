import random
import threading


TEAM_MODES = ("random", "participant", "host")


class TeamManager:
    """Reusable team assignment state for lobby-based games."""

    def __init__(self, mode="random", team_count=2):
        self._lock = threading.RLock()
        self.mode = mode if mode in TEAM_MODES else "random"
        self.team_count = max(1, min(8, int(team_count)))
        self.team_names = [f"{index}팀" for index in range(1, self.team_count + 1)]
        self.participants = {}
        self.assignments = {}

    def set_participants(self, participants):
        """Replace participants with {client_id: name}, preserving known assignments."""
        with self._lock:
            self.participants = dict(participants)
            valid_ids = set(self.participants)
            self.assignments = {
                client_id: team_id
                for client_id, team_id in self.assignments.items()
                if client_id in valid_ids
                and isinstance(team_id, int)
                and 1 <= team_id <= self.team_count
            }
            if self.mode == "random":
                unassigned = [
                    client_id
                    for client_id in self.participants
                    if client_id not in self.assignments
                ]
                random.shuffle(unassigned)
                assigned_count = len(self.assignments)
                for index, client_id in enumerate(unassigned):
                    self.assignments[client_id] = (
                        (assigned_count + index) % self.team_count + 1
                    )

    def configure(self, mode, team_count, team_names=None):
        if mode not in TEAM_MODES:
            return False, "팀 구성 방식을 올바르게 선택해 주세요."
        if isinstance(team_count, bool) or not isinstance(team_count, int):
            return False, "팀 수가 올바르지 않습니다."
        if not 1 <= team_count <= 8:
            return False, "팀 수는 1개에서 8개 사이여야 합니다."

        names = []
        if team_names is not None:
            if not isinstance(team_names, list):
                return False, "팀 이름이 올바르지 않습니다."
            names = [str(name).strip()[:12] for name in team_names]
        if len(names) != team_count:
            names = [f"{index}팀" for index in range(1, team_count + 1)]

        with self._lock:
            self.mode = mode
            self.team_count = team_count
            self.team_names = [name or f"{index}팀" for index, name in enumerate(names, 1)]
            self.assignments = {}
            if mode == "random":
                self._assign_random_locked()
        return True, None

    def assign(self, client_id, team_id):
        with self._lock:
            if client_id not in self.participants:
                return False, "참가자를 찾을 수 없습니다."
            if not isinstance(team_id, int) or isinstance(team_id, bool):
                return False, "팀을 올바르게 선택해 주세요."
            if not 1 <= team_id <= self.team_count:
                return False, "팀 번호가 올바르지 않습니다."
            self.assignments[client_id] = team_id
        return True, None

    def choose_team(self, client_id, team_id):
        with self._lock:
            if self.mode != "participant":
                return False, "현재는 참가자가 팀을 선택할 수 없습니다."
            return self.assign(client_id, team_id)

    def randomize(self):
        with self._lock:
            self.assignments = {}
            self._assign_random_locked()

    def _assign_random_locked(self):
        client_ids = list(self.participants)
        random.shuffle(client_ids)
        for index, client_id in enumerate(client_ids):
            self.assignments[client_id] = index % self.team_count + 1

    def host_state(self):
        with self._lock:
            teams = []
            for team_id, team_name in enumerate(self.team_names, 1):
                members = [
                    {"id": client_id, "name": name}
                    for client_id, name in self.participants.items()
                    if self.assignments.get(client_id) == team_id
                ]
                teams.append({
                    "id": team_id,
                    "name": team_name,
                    "members": members,
                })
            unassigned = [
                {"id": client_id, "name": name}
                for client_id, name in self.participants.items()
                if client_id not in self.assignments
            ]
            participants = [
                {
                    "id": client_id,
                    "name": name,
                    "team_id": self.assignments.get(client_id),
                }
                for client_id, name in self.participants.items()
            ]
            return {
                "mode": self.mode,
                "team_count": self.team_count,
                "teams": teams,
                "unassigned": unassigned,
                "participants": participants,
            }

    def participant_state(self, client_id):
        with self._lock:
            team_id = self.assignments.get(client_id)
            own_team = None
            if team_id is not None:
                own_team = {
                    "id": team_id,
                    "name": self.team_names[team_id - 1],
                    "members": [
                        {"id": member_id, "name": name}
                        for member_id, name in self.participants.items()
                        if self.assignments.get(member_id) == team_id
                    ],
                }
            teams = [
                {
                    "id": index,
                    "name": name,
                    "member_count": sum(
                        assigned_team == index
                        for assigned_team in self.assignments.values()
                    ),
                }
                for index, name in enumerate(self.team_names, 1)
            ]
            return {
                "mode": self.mode,
                "team_count": self.team_count,
                "team": own_team,
                "teams": teams,
            }
