"""
DQN 에이전트.

팀 확정 하이퍼파라미터:
  활성화 함수 : SiLU (Swish)
  최적화      : Adam lr=0.001
  손실 함수   : MSE (Bellman 오차)
  할인율(γ)  : 0.95
"""
import random
from collections import deque

import numpy as np
import torch
import torch.nn as nn


class QNetwork(nn.Module):
    def __init__(self, state_dim: int, action_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, 128), nn.SiLU(),
            nn.Linear(128, 128),       nn.SiLU(),
            nn.Linear(128, action_dim),
        )

    def forward(self, x):
        return self.net(x)


class DQNAgent:

    def __init__(self, state_dim: int, action_dim: int,
                 lr=0.001, gamma=0.95, epsilon=1.0,
                 epsilon_min=0.01, epsilon_decay=0.995, buffer_size=10000):
        self.action_dim    = action_dim
        self.gamma         = gamma
        self.epsilon       = epsilon
        self.epsilon_min   = epsilon_min
        self.epsilon_decay = epsilon_decay

        self.q_net      = QNetwork(state_dim, action_dim)
        self.target_net = QNetwork(state_dim, action_dim)
        self.target_net.load_state_dict(self.q_net.state_dict())

        self.optimizer = torch.optim.Adam(self.q_net.parameters(), lr=lr)
        self.loss_fn   = nn.MSELoss()
        self.buffer    = deque(maxlen=buffer_size)

    def act(self, state: np.ndarray) -> int:
        """epsilon-greedy 행동 선택."""
        if random.random() < self.epsilon:
            return random.randint(0, self.action_dim - 1)
        with torch.no_grad():
            return int(self.q_net(torch.FloatTensor(state)).argmax())

    def store(self, state, action, reward, next_state, done):
        self.buffer.append((state, action, reward, next_state, done))

    def train_step(self, batch_size=32):
        if len(self.buffer) < batch_size:
            return None
        batch = random.sample(self.buffer, batch_size)
        s, a, r, ns, d = zip(*batch)

        s  = torch.FloatTensor(np.array(s))
        a  = torch.LongTensor(a)
        r  = torch.FloatTensor(r)
        ns = torch.FloatTensor(np.array(ns))
        d  = torch.FloatTensor(d)

        q_curr = self.q_net(s).gather(1, a.unsqueeze(1)).squeeze()
        q_tgt  = r + self.gamma * self.target_net(ns).max(1)[0] * (1 - d)

        loss = self.loss_fn(q_curr, q_tgt.detach())
        self.optimizer.zero_grad(); loss.backward(); self.optimizer.step()

        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        return float(loss)

    def sync_target(self):
        self.target_net.load_state_dict(self.q_net.state_dict())
