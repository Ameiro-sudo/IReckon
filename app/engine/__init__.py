__all__ = [
    "role_registry",
    "register_role",
    "meeting_room_manager",
    "MeetingRoom",
    "MessageLayer",
    "WorkflowEngine",
    "TaskState",
    "TaskStatus",
    "task_manager",
    "TaskBoard",
    "TaskBoardState",
    "TaskPhase",
    "loop_detector",
]

_import_map = {
    "role_registry": ("app.engine.registry", "role_registry"),
    "register_role": ("app.engine.registry", "register_role"),
    "meeting_room_manager": ("app.engine.room", "meeting_room_manager"),
    "MeetingRoom": ("app.engine.room", "MeetingRoom"),
    "MessageLayer": ("app.engine.room", "MessageLayer"),
    "WorkflowEngine": ("app.engine.machine", "WorkflowEngine"),
    "TaskState": ("app.engine.tasks", "TaskState"),
    "TaskStatus": ("app.engine.tasks", "TaskStatus"),
    "task_manager": ("app.engine.tasks", "task_manager"),
    "TaskBoard": ("app.engine.board", "TaskBoard"),
    "TaskBoardState": ("app.engine.board", "TaskBoardState"),
    "TaskPhase": ("app.engine.board", "TaskPhase"),
    "loop_detector": ("app.engine.detector", "loop_detector"),
}

def __getattr__(name):
    if name in _import_map:
        import sys
        module_name, attr_name = _import_map[name]
        module = __import__(module_name, fromlist=[attr_name])
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
