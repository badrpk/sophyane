from sophyane.game_validation import (
    _snake_has_mobile_input,
    _snake_has_reverse_guard,
    _snake_has_single_timer_policy,
    _snake_problem,
)


STABLE_HTML = """<!doctype html><html><head><meta name='viewport' content='width=device-width'><style>canvas,button{touch-action:none}</style></head><body><canvas></canvas><button>Up</button><button>Down</button><button>Left</button><button>Right</button><script>
let snake=[{x:3,y:3}],dx=1,dy=0,timer;
function changeDirection(key){const goingLeft=dx===-1,goingRight=dx===1,goingUp=dy===-1,goingDown=dy===1;if(key==='left'&&!goingRight){dx=-1;dy=0}if(key==='right'&&!goingLeft){dx=1;dy=0}if(key==='up'&&!goingDown){dx=0;dy=-1}if(key==='down'&&!goingUp){dx=0;dy=1}}
function update(){snake.unshift({x:snake[0].x+dx,y:snake[0].y+dy});snake.pop()}
function start(){if(timer)clearInterval(timer);timer=setInterval(update,120)}
document.addEventListener('keydown',e=>changeDirection(e.key));document.querySelectorAll('button').forEach(b=>b.addEventListener('pointerdown',e=>{e.preventDefault();changeDirection(b.textContent.toLowerCase())}));
</script></body></html>"""


def test_stable_snake_contract_passes() -> None:
    assert _snake_problem(STABLE_HTML, "make snake game") == ""


def test_reverse_guard_is_required() -> None:
    source = "let dx=1,dy=0;function change(k){if(k==='left'){dx=-1}}"
    assert not _snake_has_reverse_guard(source)


def test_single_timer_policy_requires_clear_interval() -> None:
    assert not _snake_has_single_timer_policy("setInterval(update,100)")
    assert _snake_has_single_timer_policy("clearInterval(timer);timer=setInterval(update,100)")


def test_mobile_input_requires_touch_protection() -> None:
    html = "<button>Up</button><button>Down</button><button>Left</button><button>Right</button>"
    source = "button.addEventListener('click',move)"
    assert not _snake_has_mobile_input(html, source)
    assert _snake_has_mobile_input(html + "<style>button{touch-action:none}</style>", source)


def test_unstable_snake_is_rejected_with_actionable_reason() -> None:
    html = """<html><body><canvas></canvas><button>Up</button><button>Down</button><button>Left</button><button>Right</button><script>
let snake=[];function update(){snake.unshift({x:1,y:1})}setInterval(update,100);document.addEventListener('keydown',()=>{});button.addEventListener('click',()=>{});
</script></body></html>"""
    assert _snake_problem(html, "make snake game") == "snake controls allow unstable 180-degree reversal"
