from bdd.utils import in_zone, DETECTION_RADIUS_DEG


class EventChecker:
    @staticmethod
    def intruder_detected(state):
        a = state.agents.get('usv', {}).get('pos')
        b = state.agents.get('intru', {}).get('pos')
        if a is None or b is None:
            return False
        return in_zone(a, b, DETECTION_RADIUS_DEG)
