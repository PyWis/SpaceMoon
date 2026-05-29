def calculate_points(time_taken: float, is_correct: bool) -> int:
    """Score: 10pts if ≤30s, decays 1pt per 3s after, 0 if >60s or wrong."""
    if not is_correct or time_taken is None or time_taken > 60:
        return 0
    if time_taken <= 30:
        return 10
    delay = time_taken - 30
    points = 10 - int(delay / 3)
    return max(0, points)


def calculate_team_bonuses(session, team, round_number):
    """Check En Plein and Role bonuses for a team in a given round.

    Returns list of (bonus_type, points) tuples.
    """
    from app.models import Answer, RoundAssignment, Question

    bonuses = []
    members = [m for m in team.members if not m.is_superadmin]
    if not members:
        return bonuses

    # Gather assignments and answers for this round
    assignments = RoundAssignment.query.filter_by(
        session_id=session.id,
        round_number=round_number,
    ).filter(RoundAssignment.user_id.in_([m.id for m in members])).all()

    assignment_map = {a.user_id: a.question_id for a in assignments}

    answers = Answer.query.filter_by(round_number=round_number).filter(
        Answer.user_id.in_([m.id for m in members])
    ).all()
    answer_map = {a.user_id: a for a in answers}

    # En Plein: all members answered correctly
    all_correct = all(
        answer_map.get(m.id) and answer_map[m.id].is_correct
        for m in members
    )
    if all_correct and len(members) > 0:
        bonuses.append(('en_plein', 10))

    # Role bonus: find bonus_role for this round's question
    # Use the first question found for this round (all members may differ)
    bonus_roles_in_round = set()
    for a in assignments:
        q = Question.query.get(a.question_id)
        if q and q.bonus_role:
            bonus_roles_in_round.add(q.bonus_role)

    for bonus_role in bonus_roles_in_round:
        role_members = [m for m in members if m.role == bonus_role]
        if not role_members:
            continue
        role_all_correct = all(
            answer_map.get(m.id) and answer_map[m.id].is_correct
            for m in role_members
        )
        if role_all_correct:
            bonuses.append(('role_bonus', 10))

    return bonuses
