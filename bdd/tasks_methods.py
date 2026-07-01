import gtpyhop

def aller_m(state, agent, pos):
    return [('send_mas_cmd', agent, pos)]

def veille_m(state, agent):
    return False

def suivre_m(state, agent, target):
    import main
    pos = main.tracker.get(target)
    if pos is None:
        return False
    last = main._last_sent.get(agent)
    if last and main.in_zone({'lat': last[0], 'lon': last[1]}, pos, main.MIN_MOVE_DEG):
        return False
    main._last_sent[agent] = (pos['lat'], pos['lon'])
    return [('send_mas_cmd', agent, (pos['lat'], pos['lon']))]

gtpyhop.declare_task_methods('aller', aller_m)
gtpyhop.declare_task_methods('veille', veille_m)
gtpyhop.declare_task_methods('suivre', suivre_m)
