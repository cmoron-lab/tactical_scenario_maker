import math

import gtpyhop


def spawn_vessel(node, vessel, init_pos, model, linear_velocities_limits, angular_velocities_limits,
                  heading=0.0):
    from rclpy.action import ActionClient
    from geographic_msgs.msg import GeoPoint
    from lotusim_msgs.msg import MASCmd as MASCmdMsg
    from lotusim_msgs.action import MASCmd
    import main

    spawn = ActionClient(node, MASCmd, "/lotusim/mas_cmd")
    spawn.wait_for_server()

    cmd = MASCmdMsg()
    cmd.cmd_type    = MASCmdMsg.CREATE_CMD
    cmd.model_name  = model
    cmd.vessel_name = vessel
    cmd.geo_point   = GeoPoint(latitude=init_pos[0], longitude=init_pos[1], altitude=0.0)
    # MASCmd.heading is a top-level field (radians, used directly as yaw by entity_spawner.cpp) —
    # not an SDF tag. `heading` here is in degrees (matching the scenario/UI convention), so convert.
    cmd.heading     = math.radians(heading)
    cmd.sdf_string  = f"""
        <lotus_param>
            <waypoint_follower>
                <follower>
                    <loop>false</loop>
                    <range_tolerance>2</range_tolerance>
                    <linear_velocities_limits>{linear_velocities_limits[0]} {linear_velocities_limits[1]}</linear_velocities_limits>
                    <angular_velocities_limits>{angular_velocities_limits}</angular_velocities_limits>
                </follower>
            </waypoint_follower>
        </lotus_param>
    """
    goal = MASCmd.Goal()
    goal.cmd = cmd
    fut = spawn.send_goal_async(goal)
    main._wait(fut, timeout=10.0)
    if not fut.done() or fut.result() is None:
        raise RuntimeError(f"spawn_vessel: pas de réponse pour '{vessel}'")
    res_fut = fut.result().get_result_async()
    main._wait(res_fut, timeout=10.0)
    if not res_fut.done() or res_fut.result() is None:
        raise RuntimeError(f"spawn_vessel: timeout résultat pour '{vessel}'")
    node.get_logger().info(f"Spawned: {res_fut.result().result.name}")


def aller_a(state, agent, pos):
    """Action pure : met à jour le state (simulation, pas de ROS)."""
    state.agents[agent]['pos'] = {'lat': pos[0], 'lon': pos[1]}
    state.agents[agent]['last_waypoint'] = pos
    return state


def c_aller_a(state, agent, pos):
    """Command : envoie le waypoint ROS et met à jour le state."""
    from geographic_msgs.msg import GeoPoint
    from lotusim_msgs.srv import SetWaypoints
    import main

    node = main._ros_node
    cli = node.create_client(SetWaypoints, f"/lotusim/{agent}/waypoints")
    cli.wait_for_service()
    req = SetWaypoints.Request()
    req.path = [GeoPoint(latitude=pos[0], longitude=pos[1], altitude=0.0)]
    req.loop = False
    fut = cli.call_async(req)
    main._wait(fut)
    node.get_logger().info(f"[{agent}] → ({pos[0]:.5f}, {pos[1]:.5f})")
    if main._waypoint_log:
        with main._waypoint_log_lock:
            main._waypoint_log[0].writerow([main._ts(), agent, pos[0], pos[1]])
            main._waypoint_log[1].flush()

    state.agents[agent]['pos'] = {'lat': pos[0], 'lon': pos[1]}
    state.agents[agent]['last_waypoint'] = pos
    return state


gtpyhop.declare_actions(aller_a)
gtpyhop.declare_commands(c_aller_a)
