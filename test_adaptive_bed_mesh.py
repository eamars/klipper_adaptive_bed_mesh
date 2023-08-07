import unittest
from unittest import mock
from adaptive_bed_mesh import AdaptiveBedMesh
import os
import glob

dir_path = os.path.dirname(os.path.realpath(__file__))
test_data_dir = os.path.join(dir_path, 'test_data')


class TestAdaptiveBedMesh(unittest.TestCase):
    def setUp(self) -> None:
        # Mock mocked_bed_mesh_config
        self.mocked_bed_mesh_config = mock.MagicMock()
        self.mocked_bed_mesh_config.getfloatlist.side_effect = self.mocked_getfloatlist
        self.mocked_bed_mesh_config.getfloat.side_effect = self.mocked_get_float
        self.mocked_bed_mesh_config.get.side_effect = lambda name, default: default

        # Mock mocked_virtual_sdcard_config
        self.mocked_virtual_sdcard_config = mock.MagicMock()
        self.mocked_virtual_sdcard_config.get.return_value = 'my_path'

        # Mock config
        self.mocked_config = mock.MagicMock()
        self.mocked_config.getsection.side_effect = self.mocked_get_section
        self.mocked_config.getfloat.side_effect = self.mocked_get_float
        self.mocked_config.getint.side_effect = self.mocked_get_float

        self.adaptive_bed_mesh = AdaptiveBedMesh(self.mocked_config)

    def mocked_getfloatlist(self, name, count):
        if name == 'mesh_min':
            return 0, 0
        elif name == 'mesh_max':
            return 350, 350

    def mocked_get_section(self, name):
        if name == 'bed_mesh':
            return self.mocked_bed_mesh_config
        elif name == 'virtual_sdcard':
            return self.mocked_virtual_sdcard_config

        return mock.MagicMock()

    def mocked_get_float(self, name, default):
        return default

    def test_generate_bed_mesh_with_exclude_object(self):
        exclude_objects = [{'polygon': [[68.0779, 124.505], [92.4024, 100.181], [96.645, 100.181], [149.819, 153.355], [149.819, 157.598], [125.495, 181.922], [121.252, 181.922], [68.0779, 128.748], [68.0779, 124.505]], 'name': 'INFINITY_CUBE.STL_ID_0_COPY_0', 'center': [108.949, 141.051]}, {'polygon': [[100.181, 92.4024], [124.505, 68.0779], [128.748, 68.0779], [181.922, 121.252], [181.922, 125.495], [157.598, 149.819], [153.355, 149.819], [100.181, 96.645], [100.181, 92.4024]], 'name': 'INFINITY_CUBE.STL_ID_1_COPY_0', 'center': [141.051, 108.949]}]
        mesh_min, mesh_max = self.adaptive_bed_mesh.generate_mesh_with_exclude_object(exclude_objects)

        self.assertTupleEqual(mesh_min, (68.0779, 68.0779))
        self.assertTupleEqual(mesh_max, (181.922, 181.922))

    def test_generate_bed_mesh_param_with_gcode_analysis(self):
        # Generate file list
        gcode_with_bed_mesh_min_max = {
            '2x_3d_benchy.gcode': ((18.15, 11.38), (99.11, 101.81)),
            '2x_3d_benchy_arc_fitting.gcode': ((18.15, 11.38), (99.11, 101.81)),
            '3d_benchy_arc_fitting.gcode': ((24.78, 39.75), (94.75, 80.25)),
            '3DBenchy-Voron 0.1-ABS.gcode': ((39.68, 29.24), (80.32, 98.88)),
            'G2_Cylinder_PLA_12s.gcode': ((44.63, 44.3), (96.46, 80.58)),
            'Rear Right Foot_one_piece_ABS_5h54m.gcode': ((31.11, 30.66), (86.8, 86.34)),
            'speed_benchy_how_dare_you.gcode': ((86.19, 104.75), (155.69, 145.25)),
            'V6_Plenum_Lid_ABS_8h0m.gcode': ((17.73, 16.52), (230.49, 225.55)),
            'ss_[a]_stealthburner_main_body_beta7-Voron 2.4 250-ABS.gcode': ((36.15, 38.15), (210.94, 211.86)),
            'CFFFP_[a]_stealthburner_main_body.gcode': ((111.56, 81.33), (188.44, 218.73)),
            'z-locks-200_PLA_57m7s.gcode': ((36.83, 110.53), (263.17, 188.76)),
        }

        for gcode_filename, (ref_mesh_min, ref_mesh_max) in gcode_with_bed_mesh_min_max.items():
            with self.subTest(gcode_filename):
                gcode_filepath = os.path.join(test_data_dir, gcode_filename)
                mesh_min, mesh_max = self.adaptive_bed_mesh.generate_mesh_with_gcode_analysis(gcode_filepath)
                mesh_min, mesh_max = self.adaptive_bed_mesh.apply_min_max_margin(mesh_min, mesh_max)
                mesh_min, mesh_max = self.adaptive_bed_mesh.apply_min_max_limit(mesh_min, mesh_max)

                self.assertTupleEqual(mesh_min, ref_mesh_min)
                self.assertTupleEqual(mesh_max, ref_mesh_max)

    def test_debug_gcode_analysis_plot(self):
        from matplotlib import pyplot as plt
        gcode_file = os.path.join(test_data_dir, '2x_3d_benchy.gcode')

        layer_vertices = self.adaptive_bed_mesh.get_layer_vertices(gcode_file)
        first_layer_move_vertices = layer_vertices[min(layer_vertices.keys())]

        fig = plt.figure()
        ax = fig.subplots()

        # Plot XY move on the first layer
        x_moves = []
        y_moves = []
        for move in first_layer_move_vertices:
            x_moves.append(move['X'])
            y_moves.append(move['Y'])

        ax.plot(x_moves, y_moves, label='Toolhead Move')

        # Plot print boundary
        (x_min, y_min), (x_max, y_max) = self.adaptive_bed_mesh.get_layer_min_max_before_fade(layer_vertices, 10)
        ax.plot([x_min, x_min, x_max, x_max, x_min], [y_min, y_max, y_max, y_min, y_min], label='Print Boundary')

        # Plot probe points
        mesh_min, mesh_max = self.adaptive_bed_mesh.apply_min_max_margin((x_min, y_min), (x_max, y_max))
        mesh_min, mesh_max = self.adaptive_bed_mesh.apply_min_max_limit(mesh_min, mesh_max)
        print(f'({mesh_min}, {mesh_max})')

        (num_horizontal_probes, num_vertical_probes), probe_points, relative_reference_index = self.adaptive_bed_mesh.get_probe_points(mesh_min, mesh_max)
        print(num_horizontal_probes, num_vertical_probes, relative_reference_index)

        probe_points_x, probe_points_y = zip(*probe_points)
        ax.plot(probe_points_x, probe_points_y, marker='x', linestyle='--', label='Probe points')

        zero_reference_position = probe_points[relative_reference_index]
        ax.scatter(zero_reference_position[0], zero_reference_position[1], marker='o', label='Zero Reference Point')

        # Set equal scale
        ax.set_aspect('equal', adjustable='box')
        ax.legend(*ax.get_legend_handles_labels())
        plt.show()

    def test_get_layer_vertices(self):
        gcode_filepath = os.path.join(test_data_dir, '2x_3d_benchy.gcode')

        layer_vertices = self.adaptive_bed_mesh.get_layer_vertices(gcode_filepath)

        with self.subTest('all_layers'):
            mesh_min, mesh_max = self.adaptive_bed_mesh.get_layer_min_max_before_fade(layer_vertices)
            self.assertTupleEqual(mesh_min, (23.154, 16.376))
            self.assertTupleEqual(mesh_max, (94.111, 96.81))

        with self.subTest('10_layers'):
            mesh_min, mesh_max = self.adaptive_bed_mesh.get_layer_min_max_before_fade(layer_vertices, 10)
            self.assertTupleEqual(mesh_min, (23.154, 16.381))
            self.assertTupleEqual(mesh_max, (89.637, 95.344))

    def test_apply_probe_point_limits(self):

        with self.subTest('min_probe_counts'):
            self.adaptive_bed_mesh.minimum_axis_probe_counts = 4
            num_probes = self.adaptive_bed_mesh.apply_probe_point_limits(3, 3)
            self.assertTupleEqual(num_probes, (4, 4))

        with self.subTest('lagrange'):
            self.adaptive_bed_mesh.minimum_axis_probe_counts = 3
            self.adaptive_bed_mesh.bed_mesh_config_algorithm = 'lagrange'
            num_probes = self.adaptive_bed_mesh.apply_probe_point_limits(10, 10)
            self.assertTupleEqual(num_probes, (6, 6))

        with self.subTest('bicubic'):
            self.adaptive_bed_mesh.minimum_axis_probe_counts = 3
            self.adaptive_bed_mesh.bed_mesh_config_algorithm = 'bicubic'
            num_probes = self.adaptive_bed_mesh.apply_probe_point_limits(8, 3)
            self.assertTupleEqual(num_probes, (8, 4))


if __name__ == '__main__':
    unittest.main()