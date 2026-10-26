"""Unit tests for ActorStepper."""

from unittest.mock import MagicMock
import pytest
from garuda.flight.actor_stepper import ActorStepper


def test_actor_stepper_initialization():
    mock_world = MagicMock()
    waypoints = [(-1.0, 15.0), (5.0, 15.0), (5.0, 20.0), (-1.0, 20.0)]
    stepper = ActorStepper(mock_world, "Walker1", waypoints, speed_mps=1.0)

    assert stepper.cur_x == -1.0
    assert stepper.cur_y == 15.0
    assert stepper.seg_idx == 0
    assert mock_world.set_object_pose.called


def test_actor_stepper_step_advances_position():
    mock_world = MagicMock()
    waypoints = [(-1.0, 15.0), (5.0, 15.0)]
    stepper = ActorStepper(mock_world, "Walker1", waypoints, speed_mps=2.0)

    # Step for 0.5 seconds at 2.0 m/s -> 1.0 meter advance along x
    pos = stepper.step(dt=0.5)
    assert abs(pos[0] - 0.0) < 1e-3
    assert abs(pos[1] - 15.0) < 1e-3


def test_actor_stepper_loops_at_end():
    mock_world = MagicMock()
    waypoints = [(0.0, 0.0), (1.0, 0.0)]
    stepper = ActorStepper(mock_world, "Walker1", waypoints, speed_mps=10.0)

    # Overshoot waypoint 1 -> should wrap to segment 0 or 1
    stepper.step(dt=0.2)
    assert stepper.cur_x <= 1.0


def test_actor_stepper_start_and_stop():
    import time
    mock_world = MagicMock()
    waypoints = [(0.0, 0.0), (10.0, 0.0)]
    stepper = ActorStepper(mock_world, "Walker1", waypoints, speed_mps=5.0)

    stepper.start(update_rate_hz=20.0)
    time.sleep(0.15)
    stepper.stop()

    assert stepper.cur_x > 0.0
    assert not stepper._running
