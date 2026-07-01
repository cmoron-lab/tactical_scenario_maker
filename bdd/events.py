class EventChecker:
    """Bibliothèque de conditions d'événements. Chaque @staticmethod retourne un bool."""

    @staticmethod
    def intruder_detected():
        import main
        a, b = main.tracker.get('usv'), main.tracker.get('intru')
        if a is None or b is None:
            return False
        return main.in_zone(a, b, main.DETECTION_RADIUS_DEG)
