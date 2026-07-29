import random

class SnakeGame:
    def __init__(self, width=20, height=20):
        self.width = width
        self.height = height
        self.reset()

    def reset(self):
        self.snake = [(self.width // 2, self.height // 2)]
        self.direction = (1, 0)
        self.food = self._spawn_food()
        self.score = 0
        self.game_over = False

    def _spawn_food(self):
        while True:
            x = random.randint(0, self.width - 1)
            y = random.randint(0, self.height - 1)
            if (x, y) not in self.snake:
                return (x, y)

    def step(self, action=None):
        if self.game_over:
            return self.score, True
        if action == 'UP' and self.direction != (0, 1):
            self.direction = (0, -1)
        elif action == 'DOWN' and self.direction != (0, -1):
            self.direction = (0, 1)
        elif action == 'LEFT' and self.direction != (1, 0):
            self.direction = (-1, 0)
        elif action == 'RIGHT' and self.direction != (-1, 0):
            self.direction = (1, 0)
        head_x, head_y = self.snake[0]
        dx, dy = self.direction
        new_head = (head_x + dx, head_y + dy)
        if (new_head[0] < 0 or new_head[0] >= self.width or new_head[1] < 0 or new_head[1] >= self.height or new_head in self.snake):
            self.game_over = True
            return self.score, True
        self.snake.insert(0, new_head)
        if new_head == self.food:
            self.score += 10
            self.food = self._spawn_food()
        else:
            self.snake.pop()
        return self.score, False

if __name__ == '__main__':
    game = SnakeGame()
    print('Snake Game Initialized. Score:', game.score)
