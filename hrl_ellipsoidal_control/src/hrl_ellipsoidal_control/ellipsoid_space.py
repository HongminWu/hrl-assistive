#! /usr/bin/python

import numpy as np

import roslib
roslib.load_manifest('hrl_ellipsoidal_control')
from tf import TransformBroadcaster

import hrl_geom.transformations as trans
from hrl_geom.pose_converter import PoseConv
from hrl_geom import transformations as trans
from hrl_ellipsoidal_control.controller_base import min_jerk_traj

class EllipsoidSpace(object):
    def __init__(self, E=1, is_oblate=False):
        self.A = 1
        self.E = E
        #self.B = np.sqrt(1. - E**2)
        self.a = self.A * self.E
        self.is_oblate = is_oblate
        self.center = None
        self.frame = None
        self.frame_broadcaster = TransformBroadcaster()

    def set_center(self, pose_stamped):
        self.center = pose_stamped
        def broadcast_ell_center(event):
            trans = (pose_stamped.pose.position.x,
                     pose_stamped.pose.position.y,
                     pose_stamped.pose.position.z) 
            rot = (pose_stamped.pose.orientation.x,
                   pose_stamped.pose.orientation.y,
                   pose_stamped.pose.orientation.z,
                   pose_stamped.pose.orientation.w)
            self.frame_broadcaster.sendTransform(trans, rot, rospy.Time.now(),
                                                 pose_stamped.header.frame_id,
                                                 'ellipsoid_center')
        rospy.Timer(rospy.Duration(0.01), broadcast_ell_center)

    def load_ell_params(self, E, is_oblate=False, height=1):
        self.E = E
        self.a = self.A * self.E
        self.is_oblate = is_oblate
        self.height = height

    def ellipsoidal_to_cart(self, lat, lon, height):
        #assert height > 0 and lat >= 0 and lat <= np.pi and lon >= 0 and lon < 2 * np.pi
        if not self.is_oblate:
            x = self.a * np.sinh(height) * np.sin(lat) * np.cos(lon)
            y = self.a * np.sinh(height) * np.sin(lat) * np.sin(lon)
            z = self.a * np.cosh(height) * np.cos(lat)
        else:
            x = self.a * np.cosh(height) * np.cos(lat-np.pi/2) * np.cos(lon)
            y = self.a * np.cosh(height) * np.cos(lat-np.pi/2) * np.sin(lon)
            z = self.a * np.sinh(height) * np.sin(lat-np.pi/2)
        pos_local = np.mat([x, y, z]).T
        return pos_local

    def partial_height(self, lat, lon, height):
        #assert height > 0 and lat >= 0 and lat <= np.pi and lon >= 0 and lon < 2 * np.pi
        if not self.is_oblate:
            x = self.a * np.cosh(height) * np.sin(lat) * np.cos(lon)
            y = self.a * np.cosh(height) * np.sin(lat) * np.sin(lon)
            z = self.a * np.sinh(height) * np.cos(lat)
        else:
            x = self.a * np.sinh(height) * np.sin(lat-np.pi/2) * np.cos(lon)
            y = self.a * np.sinh(height) * np.sin(lat-np.pi/2) * np.sin(lon)
            z = self.a * np.cosh(height) * np.cos(lat-np.pi/2)
        print "[ell_space] partial_height: %s" %np.mat([x,y,z]).T
        return np.mat([x, y, z]).T

    #def partial_v(self, lat, lon, height):
    #    #assert height > 0 and lat >= 0 and lat <= np.pi and lon >= 0 and lon < 2 * np.pi
    #    x = self.a * np.sinh(height) * np.cos(lat) * np.cos(lon)
    #    y = self.a * np.sinh(height) * np.cos(lat) * np.sin(lon)
    #    z = self.a * np.cosh(height) * -np.sin(lat)
    #    return np.mat([x, y, z]).T
    #def partial_p(self, lat, lon, height):
    #    #assert height > 0 and lat >= 0 and lat <= np.pi and lon >= 0 and lon < 2 * np.pi
    #    x = self.a * np.sinh(height) * np.sin(lat) * -np.sin(lon)
    #    y = self.a * np.sinh(height) * np.sin(lat) * np.cos(lon)
    #    z = 0.
    #    return np.mat([x, y, z]).T

    def ellipsoidal_to_pose(self, lat, lon, height):
        print "Finding ell_to_pose"
        if not self.is_oblate:
            return self._ellipsoidal_to_pose_prolate(lat, lon, height)
        else:
            return self._ellipsoidal_to_pose_oblate(lat, lon, height)

    def _ellipsoidal_to_pose_prolate(self, lat, lon, height):
        pos = self.ellipsoidal_to_cart(lat, lon, height)
        df_du = self.partial_height(lat, lon, height)
        nx, ny, nz = df_du.T.A[0] / np.linalg.norm(df_du)
        j = np.sqrt(1./(1.+ny*ny/(nz*nz)))
        k = -ny*j/nz
        norm_rot = np.mat([[-nx,  ny*k - nz*j,  0],      
                           [-ny,  -nx*k,        j],      
                           [-nz,  nx*j,         k]])
        _, norm_quat = PoseConv.to_pos_quat(np.mat([0, 0, 0]).T, norm_rot)
        rot_angle = np.arctan(-norm_rot[2,1] / norm_rot[2,2])
        #print norm_rot
        quat_ortho_rot = trans.quaternion_from_euler(rot_angle + np.pi, 0.0, 0.0)
        norm_quat_ortho = trans.quaternion_multiply(norm_quat, quat_ortho_rot)
        norm_rot_ortho = np.mat(trans.quaternion_matrix(norm_quat_ortho)[:3,:3])
        if norm_rot_ortho[2, 2] > 0:
            flip_axis_ang = 0
        else:
            flip_axis_ang = np.pi
        quat_flip = trans.quaternion_from_euler(flip_axis_ang, 0.0, 0.0)
        norm_quat_ortho_flipped = trans.quaternion_multiply(norm_quat_ortho, quat_flip)

        pose = PoseConv.to_pos_quat(pos, norm_quat_ortho_flipped)
        #print ("ellipsoidal_to_pose: latlonheight: %f, %f, %f" %
        #       (lat, lon, height) +
        #       str(PoseConv.to_homo_mat(pose)))
        return pose

    def _ellipsoidal_to_pose_oblate(self, lat, lon, height):
        pos = self.ellipsoidal_to_cart(lat, lon, height)
        df_du = self.partial_height(-lat, lon, height)
        nx, ny, nz = df_du.T.A[0] / np.linalg.norm(df_du)
        j = np.sqrt(1./(1.+ny*ny/(nz*nz)))
        k = -ny*j/nz
        norm_rot = np.mat([[-nx,  ny*k - nz*j,  0],      
                           [-ny,  -nx*k,        j],      
                           [-nz,  nx*j,         k]])
        _, norm_quat = PoseConv.to_pos_quat(np.mat([0, 0, 0]).T, norm_rot)
        rot_angle = np.arctan(-norm_rot[2,1] / norm_rot[2,2])
        #print norm_rot
        quat_ortho_rot = trans.quaternion_from_euler(rot_angle, 0.0, 0.0)
        norm_quat_ortho = trans.quaternion_multiply(norm_quat, quat_ortho_rot)
        quat_ortho_rot2 = trans.quaternion_from_euler(0.0, np.pi/2, 0.0)
        norm_quat_ortho = trans.quaternion_multiply(norm_quat_ortho, quat_ortho_rot2)
        if lon >= np.pi:
            quat_flip = trans.quaternion_from_euler(0.0, 0.0, np.pi)
            norm_quat_ortho = trans.quaternion_multiply(norm_quat_ortho, quat_flip)

        pose = PoseConv.to_pos_quat(pos, norm_quat_ortho)
        #print ("ellipsoidal_to_pose: latlonheight: %f, %f, %f" %
        #       (lat, lon, height) +
        #       str(PoseConv.to_homo_mat(pose)))
        return pose

    def pose_to_ellipsoidal(self, pose):
        pose_pos, pose_rot = PoseConv.to_pos_rot(pose)
        lat, lon, height = self.pos_to_ellipsoidal(pose_pos[0,0], pose_pos[1,0], pose_pos[2,0])
        _, ell_rot = PoseConv.to_pos_rot(self.ellipsoidal_to_pose(lat, lon, height))
        _, quat_rot = PoseConv.to_pos_quat(np.mat([0]*3).T, ell_rot.T * pose_rot)
        return [lat, lon, height], quat_rot

    def pos_to_ellipsoidal(self, x, y, z):
        if not self.is_oblate:
            return self._pos_to_ellipsoidal_prolate(x, y, z)
        else:
            return self._pos_to_ellipsoidal_oblate(x, y, z)

    def _pos_to_ellipsoidal_prolate(self, x, y, z):
        lon = np.arctan2(y, x)
        if lon < 0.:
            lon += 2 * np.pi
        p = np.sqrt(x**2 + y**2)
        a = self.a
        inner = np.sqrt((np.sqrt((z**2 - a**2 + p**2)**2 + (2. * a * p)**2) / a**2 -
                         (z / a)**2 - (p / a)**2 + 1) / 2.)
        assert inner < 1.0001
        if inner > 0.9999:
            lat = np.pi/2.
        else:
            lat = np.arcsin(inner)
        if z < 0.:
            lat = np.pi - np.fabs(lat)
        if np.fabs(np.sin(lat)) > 0.05:
            if np.fabs(np.cos(lon)) > 0.05:
                use_case = 'x'
                sinh_height = x / (a * np.sin(lat) * np.cos(lon))
                height = np.log(sinh_height + np.sqrt(sinh_height**2 + 1))
            else:
                use_case = 'y'
                sinh_height = y / (a * np.sin(lat) * np.sin(lon))
                height = np.log(sinh_height + np.sqrt(sinh_height**2 + 1))
        else:
            use_case = 'z'
            cosh_height = z / (a * np.cos(lat))
            assert np.fabs(cosh_height) >= 1, ("cosh_height %f, a %f, x %f, y %f, z %f, lat %f, lon %f" %
                                               (cosh_height, a, x, y, z, lat, lon))
            height = np.log(cosh_height + np.sqrt(cosh_height**2 - 1))
        print ("%s pos_to_ellipsoidal: xyz: %f, %f, %f; latlonheight: %f, %f, %f" %
               (use_case, x, y, z, lat, lon, height))
        assert not np.any(np.isnan([lat, lon, height])), ("cosh_height %f, a %f, x %f, y %f, z %f, lat %f, lon %f" %
                                               (cosh_height, a, x, y, z, lat, lon))
        return lat, lon, height

    def _pos_to_ellipsoidal_oblate(self, x, y, z):
        lon = np.arctan2(y, x)
        if lon < 0.:
            lon += 2 * np.pi
        p = np.sqrt(x**2 + y**2)
        a = self.a
        d_1 = np.sqrt((p + a)**2 + z**2)
        d_2 = np.sqrt((p - a)**2 + z**2)
        cosh_height = (d_1 + d_2) / (2 * a)
        assert np.fabs(cosh_height) >= 1, ("cosh_height %f, a %f, x %f, y %f, z %f, lat %f, lon %f" %
                                           (cosh_height, a, x, y, z, lat, lon))
        height = np.log(cosh_height + np.sqrt(cosh_height**2 - 1))
        cos_lat = (d_1 - d_2) / (2 * a)
        lat = np.arccos(cos_lat)
        if z < 0.:
            lat *= -1

        # we're going to convert the latitude coord so it is always positive:
        lat += np.pi / 2.

        return lat, lon, height


#   def _create_ell_trajectory(self, ell_f, rot_mat_f, orient_quat=[0., 0., 0., 1.], velocity=0.001):
    def create_ellipsoidal_path(self, end_ell_pos, end_ell_rot,
                                       start_ell_pos, start_ell_rot,
                                       orient_quat=[0.,0.,0.,1.], velocity=0.001):
        #_, cur_rot = PoseConv.to_pos_rot(self.arm.get_ep())

        rpy = trans.euler_from_matrix(start_ell_rot.T * end_ell_rot) # get roll, pitch, yaw of angle diff
  #      print "RPY DIFF: %s, %s, %s" %(rpy[0], rpy[1], rpy[2])
  #      print "end_ell_pos: \r\n%s" %end_ell_pos
  #      print "end_ell_rot: \r\n%s" %end_ell_rot
  #      print "start_ell_pos: \r\n%s" %start_ell_pos
  #      print "start_ell_rot: \r\n%s" %start_ell_rot
        end_ell_pos[1] = np.mod(end_ell_pos[1], 2 * np.pi) # wrap longitude value
  #      print "Wrapped lon value: %s" %end_ell_pos[1]

        # get the current ellipsoidal location of the end effector
        ell_init = np.mat(start_ell_pos).T 
        ell_final = np.mat(end_ell_pos).T
  #      print "Ell init: %s" %ell_init
  #      print "Ell final: %s" %ell_final

        # find the closest longitude angle to interpolate to
        if np.fabs(2 * np.pi + ell_final[1,0] - ell_init[1,0]) < np.pi:
            ell_final[1,0] += 2 * np.pi
        elif np.fabs(-2 * np.pi + ell_final[1,0] - ell_init[1,0]) < np.pi:
            ell_final[1,0] -= 2 * np.pi
        if np.any(np.isnan(ell_init)) or np.any(np.isnan(ell_final)):
            rospy.logerr("[ellipsoid_space] Nan values in ellipsoid. " +
                         "ell_init: %f, %f, %f; " % (ell_init[0,0], ell_init[1,0], ell_init[2,0]) +
                         "ell_final: %f, %f, %f; " % (ell_final[0,0], ell_final[1,0], ell_final[2,0]))
            return None
        
        num_samps = np.max([2, int(np.linalg.norm(ell_final - ell_init) / velocity), 
                               int(np.linalg.norm(rpy) / velocity)])
  #      print "Number of interp samples: %s" %num_samps
        
        t_vals = min_jerk_traj(num_samps)
  #      print "Time interp values: %s" %t_vals
            
        # smoothly interpolate from init to final
        ell_lat_traj = np.interp(t_vals, (0,1),(start_ell_pos[0], end_ell_pos[0]))
        ell_lon_traj = np.interp(t_vals, (0,1),(start_ell_pos[1], end_ell_pos[1]))
        ell_height_traj = np.interp(t_vals, (0,1),(start_ell_pos[2], end_ell_pos[2]))
        ell_pos_traj = np.vstack((ell_lat_traj, ell_lon_traj, ell_height_traj))

#        print "Pos Traj: %s" %ell_pos_traj
        start_quat = trans.quaternion_from_matrix(start_ell_rot)
#        print "Start Quat: (%s,%s,%s,%s)" %(start_quat[0], start_quat[1], start_quat[2], start_quat[3])
        end_quat = trans.quaternion_from_matrix(end_ell_rot)
#        print "End Quat: (%s,%s,%s,%s)" %(end_quat[0], end_quat[1], end_quat[2], end_quat[3])
        ell_quat_traj = [trans.quaternion_slerp(start_quat, end_quat, t) for t in t_vals]
        ell_rot_traj = [trans.quaternion_matrix(quat)[:3,:3] for quat in ell_quat_traj]
#        print "Rotation Trajectory: %s" %ell_rot_traj
#        print "shape of pos traj: ", ell_pos_traj.shape
#        print "shape of rot traj: ", len(ell_rot_traj)
        return [[ell_pos_traj[:,i],ell_rot_traj[i]] for i in xrange(num_samps)]
#        print "Pose 0:", ell_poses[0]
#        print "Pose 100:", ell_poses[100]
#        print "Last Pose: ", ell_poses[-1]

#        ell_frame_mat = self.ell_server.get_ell_frame()
#
#        ell_pose_traj = [self.ell_server.robot_ellipsoidal_pose(
#                            ell_traj[0,i], ell_traj[1,i], ell_traj[2,i], orient_quat, ell_frame_mat) 
#                         for i in range(ell_traj.shape[1])]
#
        # modify rotation of trajectory
#        _, ell_init_rot = self.ell_server.robot_ellipsoidal_pose(
#                ell_init[0,0], ell_init[1,0], ell_init[2,0], orient_quat, ell_frame_mat)
#        rot_adjust_traj = self.arm.interpolate_ep([np.mat([0]*3).T, start_ell_rot], 
#                                                  [np.mat([0]*3).T, end_ell_rot], 
#                                                  min_jerk_traj(num_samps))
#        ell_pose_traj = [(ell_pose_traj[i][0], 
#                          ell_pose_traj[i][1] * ell_init_rot.T * rot_adjust_traj[i][1]) 
#                         for i in range(num_samps)]
#
#        return ell_pose_traj
        
def main():
    e_space = EllipsoidSpace(1)
    # test pos_to_ellipsoidal
    for xm in range(2):
        for ym in range(2):
            for zm in range(2):
                for i in range(10000):
                    x, y, z = np.random.uniform(-2.5, 2.5, 3)
                    lat, lon, height = e_space.pos_to_ellipsoidal(xm*x, ym*y, zm*z)
                    assert lat >= 0 and lat <= np.pi*1.0001, ("latlonheight: %f, %f, %f" %
                                                       (lat, lon, height))
                    assert lon >= 0 and lon < 2*np.pi*1.0001, ("latlonheight: %f, %f, %f" %
                                                       (lat, lon, height))
                    assert height >= 0, ("latlonheight: %f, %f, %f" %
                                                       (lat, lon, height))
                    #print lat, lon, height

if __name__ == "__main__":
    main()
