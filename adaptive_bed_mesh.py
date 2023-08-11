import configparser
import numpy
import math
from contextlib import contextmanager
import traceback
import os


class AdaptiveBedMesh(object):
    def __init__(self, config):
        self._move_gcmd_interpreter = {'G0': self._move_gcmd_decoder,
                                       'G1': self._move_gcmd_decoder,
                                       'G2': self._arc_move_gcmd_decoder,
                                       'G3': self._arc_move_gcmd_decoder}

        # Read user configurations
        self.arc_segments = config.getint('arc_segments', 80)
        self.mesh_area_clearance = config.getfloat('mesh_area_clearance', 5)
        self.max_probe_horizontal_distance = config.getfloat('max_probe_horizontal_distance', 50)
        self.max_probe_vertical_distance = config.getfloat('max_probe_vertical_distance', 50)
        self.use_relative_reference_index = config.getboolean('use_relative_reference_index', False)

        # Enable/Disable boundary detection
        self.disable_slicer_min_max_boundary_detection = config.getboolean('disable_slicer_min_max_boundary_detection', False)
        self.disable_exclude_object_boundary_detection = config.getboolean('disable_exclude_object_boundary_detection', False)
        self.disable_gcode_analysis_boundary_detection = config.getboolean('disable_gcode_analysis_boundary_detection', False)

        # Debug options
        # By enabling the `debug_mode` the Python exception won't cause Klipper to shutdown
        self.debug_mode = config.getboolean('debug_mode', False)

        # Some constants
        self.minimum_axis_probe_counts = 3

        # Read klipper objects
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')

        # Prompt the user for the order of declaration error
        try:
            self.exclude_object = self.printer.lookup_object('exclude_object')
        except configparser.Error:
            raise configparser.Error("[adaptive_bed_mesh] need to be declared after [exclude_object]")

        try:
            self.print_stats = self.printer.lookup_object('print_stats')
        except configparser.Error:
            raise configparser.Error("[adaptive_bed_mesh] need to be declared after [print_stats]")

        try:
            self.bed_mesh = self.printer.lookup_object('bed_mesh')
        except configparser.Error:
            raise configparser.Error("[adaptive_bed_mesh] need to be declared after [bed_mesh]")

        # Register commands
        self.gcode.register_command('ADAPTIVE_BED_MESH_CALIBRATE',
                                    self.cmd_ADAPTIVE_BED_MESH_CALIBRATE,
                                    desc='Run the adaptive bed mesh based on either the user input or the loaded gcode')

        # Read [bed_mesh] section information
        self.bed_mesh_config = config.getsection('bed_mesh')
        self.bed_mesh_config_mesh_min = self.bed_mesh_config.getfloatlist('mesh_min', count=2)
        self.bed_mesh_config_mesh_max = self.bed_mesh_config.getfloatlist('mesh_max', count=2)
        self.bed_mesh_config_fade_end = self.bed_mesh_config.getfloat('fade_end', 0)
        self.bed_mesh_config_algorithm = self.bed_mesh_config.get('algorithm', 'lagrange').strip().lower()

        # Read [virtual_sdcard] section information
        self.virtual_sdcard_config = config.getsection('virtual_sdcard')
        sd = self.virtual_sdcard_config.get('path')
        self.virtual_sdcard_path = os.path.normpath(os.path.expanduser(sd))

    def log_to_gcmd_respond(self, gcmd, text):
        gcmd.respond_info("AdaptiveBedMesh:" + text)

    @contextmanager
    def catch_exception_to_console(self, gcmd):
        try:
            yield
        except Exception as e:
            self.log_to_gcmd_respond(gcmd, "Caught exception: {}, \nCallstack:\n---------------\n{}".format(e, traceback.format_exc()))
            if not self.debug_mode:
                raise

    def cmd_ADAPTIVE_BED_MESH_CALIBRATE(self, gcmd):
        with self.catch_exception_to_console(gcmd):
            while True:
                # Method 1: Slicer min max boundary detection
                if not self.disable_slicer_min_max_boundary_detection:
                    self.log_to_gcmd_respond(gcmd, "Attempting to detect boundary by slicer min max")
                    area_start = gcmd.get("AREA_START", default=None)
                    area_end = gcmd.get("AREA_END", default=None)
                    if area_start is not None and area_end is not None:
                        mesh_min = [float(s) for s in area_start.split(',')]
                        mesh_max = [float(s) for s in area_end.split(',')]
                        self.log_to_gcmd_respond(gcmd, "Use min max boundary detection")
                        break
                    else:
                        self.log_to_gcmd_respond(gcmd, "Failed to run slicer min max: No information available")

                # Method 2: Exclude object boundary detection
                if not self.disable_exclude_object_boundary_detection:
                    self.log_to_gcmd_respond(gcmd, "Attempting to detect boundary by exclude boundary")
                    try:
                        if self.debug_mode:
                            self.log_to_gcmd_respond(gcmd, str(self.exclude_object.objects))

                        if self.exclude_object.objects:
                            mesh_min, mesh_max = self.generate_mesh_with_exclude_object(self.exclude_object.objects)
                            self.log_to_gcmd_respond(gcmd, "Use exclude object boundary detection")
                            break
                        else:
                            self.log_to_gcmd_respond(gcmd, "Failed to run exclude object analysis: No exclude object information available")
                    except Exception as e:
                        self.log_to_gcmd_respond(gcmd, "Failed to run exclude object analysis: {}".format(e))

                # Method 3: Gcode analysis boundary detection
                if not self.disable_gcode_analysis_boundary_detection:
                    self.log_to_gcmd_respond(gcmd, "Attempting to detect boundary by Gcode analysis")
                    try:
                        gcode_filepath = gcmd.get("GCODE_FILEPATH", None)
                        mesh_min, mesh_max = self.generate_mesh_with_gcode_analysis(gcode_filepath)
                        self.log_to_gcmd_respond(gcmd, "Use Gcode analysis boundary detection")
                        break
                    except Exception as e:
                        self.log_to_gcmd_respond(gcmd, "Failed to run Gcode analysis: {}".format(e))

                self.log_to_gcmd_respond(gcmd, "Fallback to default bed mesh")
                # Method 4: use default bed mesh settings
                mesh_min = self.bed_mesh_config_mesh_min
                mesh_max = self.bed_mesh_config_mesh_max

                break

            if self.debug_mode:
                self.log_to_gcmd_respond(gcmd, "mesh_min: {}, mesh_max: {}".format(mesh_min, mesh_max))
                self.log_to_gcmd_respond(gcmd, "mesh_area_clearance: {}".format(self.mesh_area_clearance))

            # Apply the bed mesh margin and limit, then generate the bed_mesh_calibrate parameter
            params = self.generate_bed_mesh_params(mesh_min, mesh_max)

            cmd = "BED_MESH_CALIBRATE {}".format(params)
            self.log_to_gcmd_respond(gcmd, cmd)

            self.gcode.run_script_from_command(cmd)

    def generate_bed_mesh_params(self, mesh_min, mesh_max):
        # Apply margin
        mesh_min, mesh_max = self.apply_min_max_margin(mesh_min, mesh_max)

        # Apply min max limit based on bed mesh config
        mesh_min, mesh_max = self.apply_min_max_limit(mesh_min, mesh_max)

        # Generate mesh min and max
        (num_horizontal_probes, num_vertical_probes), probe_points, relative_reference_index = self.get_probe_points(mesh_min, mesh_max)

        zero_reference_position = probe_points[relative_reference_index]

        params = "MESH_MIN={x_min},{y_min} MESH_MAX={x_max},{y_max} PROBE_COUNT={x_counts},{y_counts}".format(
            x_min=mesh_min[0], y_min=mesh_min[1], x_max=mesh_max[0], y_max=mesh_max[1],
            x_counts=num_horizontal_probes, y_counts=num_vertical_probes
        )

        if self.use_relative_reference_index:
            params += ' relative_reference_index={}'.format(relative_reference_index)
        else:
            self.bed_mesh.zero_ref_pos = zero_reference_position

        return params

    def generate_mesh_with_exclude_object(self, objects):
        object_min_max_list = []
        for obj in objects:
            mesh_min, mesh_max = self.get_polygon_min_max(obj['polygon'])
            object_min_max_list.append(mesh_min)
            object_min_max_list.append(mesh_max)

        mesh_min, mesh_max = self.get_polygon_min_max(object_min_max_list)

        return mesh_min, mesh_max

    def generate_mesh_with_gcode_analysis(self, gcode_filepath=None):
        if gcode_filepath is None:
            curtime = self.printer.get_reactor().monotonic()
            filename = self.print_stats.get_status(curtime)['filename']
            gcode_filepath = os.path.join(self.virtual_sdcard_path, filename)

        layer_vertices = self.get_layer_vertices(gcode_filepath)
        mesh_min, mesh_max = self.get_layer_min_max_before_fade(layer_vertices, self.bed_mesh_config_fade_end)

        return mesh_min, mesh_max

    def apply_min_max_limit(self, coord_min, coord_max):
        x_min = max(round(coord_min[0], 2), self.bed_mesh_config_mesh_min[0])
        y_min = max(round(coord_min[1], 2), self.bed_mesh_config_mesh_min[1])

        x_max = min(round(coord_max[0], 2), self.bed_mesh_config_mesh_max[0])
        y_max = min(round(coord_max[1], 2), self.bed_mesh_config_mesh_max[1])

        return (x_min, y_min), (x_max, y_max)

    def _move_gcmd_decoder(self, gcmd, current_coordinate=None):
        new_move = {'X': None, 'Y': None, 'Z': None, 'E': None, 'F': None}  # minimum params you need
        for param in gcmd:
            param_prefix = param[0].upper()
            try:
                new_move[param_prefix] = float(param[1:])
            except ValueError:
                raise ValueError('Unable to convert gcmd {}'.format(gcmd))

        return [new_move]

    def _arc_move_gcmd_decoder(self, gcmd, current_coordinate):
        gcode_params = self._move_gcmd_decoder(gcmd, current_coordinate)[0]

        start_coord = (current_coordinate['X'], current_coordinate['Y'])

        # TODO: If the gcode specifies P<n> then X and Y are not necessary output. Need to natively support P<n>
        #   instead of assuming X and Y will be omitted.

        end_coord = (gcode_params['X'] if gcode_params['X'] is not None else current_coordinate['X'],
                     gcode_params['Y'] if gcode_params['Y'] is not None else current_coordinate['Y'])

        center_coord = (start_coord[0] + gcode_params['I'], start_coord[1] + gcode_params['J'])

        if 'R' in gcode_params:
            radius = gcode_params['R']
        else:
            radius = math.hypot(gcode_params['I'], gcode_params['J'])

        start_angle = math.atan2(start_coord[1] - center_coord[1], start_coord[0] - center_coord[0])
        end_angle = math.atan2(end_coord[1] - center_coord[1], end_coord[0] - center_coord[0])

        angle_delta = end_angle - start_angle
        if 'G3' in gcmd:
            if angle_delta < 0:
                angle_delta += 2 * math.pi
        elif 'G2' in gcmd:
            if angle_delta > 0:
                angle_delta -= 2 * math.pi

        angle_increment = angle_delta / self.arc_segments

        # Generate points on the arc
        arc_points = []
        for i in range(self.arc_segments + 1):
            angle = start_angle + (angle_increment * i)
            x = center_coord[0] + radius * math.cos(angle)
            y = center_coord[1] + radius * math.sin(angle)
            arc_points.append({'X': x, 'Y': y, 'E': gcode_params['E'], 'F': gcode_params['F'], 'Z': gcode_params['Z']})

        return arc_points

    def get_layer_vertices(self, gcode_filepath):
        current_coordinate = dict(X=0, Y=0, Z=0)  # don't track E
        is_absolute_move = True
        extrude_layer_moves = dict()

        with open(gcode_filepath, 'r') as fp:
            while True:
                try:
                    line = fp.readline()
                except UnicodeDecodeError as e:
                    # Ignore UnicodeDecodeError (not really important)
                    continue

                if line == '':
                    break

                # Skip comment lines
                line = line.strip()

                # Nothing in front of comment
                raw_gcmd = line.split(';')[0].strip()
                if raw_gcmd == '':
                    continue

                # Decode gcode
                gcmd = raw_gcmd.split()

                # Skip empty
                if len(gcmd) == 0:
                    continue

                gcmd_header = gcmd[0].upper()

                if gcmd_header == 'G90':
                    is_absolute_move = True
                elif gcmd_header == 'G91':
                    is_absolute_move = False

                # Skip gcode that is not a motion command
                if gcmd_header not in self._move_gcmd_interpreter.keys():
                    continue

                # Decode motion command
                interpreter = self._move_gcmd_interpreter[gcmd_header]
                new_moves = interpreter(gcmd, current_coordinate)

                # Each motion command many generate one or more moves. Analyse each move
                for new_move in new_moves:
                    for key in current_coordinate.keys():
                        new_param = new_move[key]
                        if new_param is not None:
                            if is_absolute_move:
                                current_coordinate[key] = new_param
                            else:
                                current_coordinate[key] += new_param

                    # Ignore extrude only move
                    if all(new_move[p] is None for p in ['X', 'Y', 'Z']):
                        continue

                    # Register move
                    current_layer = current_coordinate['Z']

                    # 0 is either undefined or invalid move
                    if current_layer == 0:
                        continue

                    # Move to a new layer, then register the new layer
                    if current_layer not in extrude_layer_moves:
                        extrude_layer_moves[current_layer] = []

                    # Register only the extrude move
                    # FIXME: This will remove non-extrude move, result in incorrect visual representation of the gcode.
                    if new_move['E'] is not None and new_move['E'] > 0:
                        extrude_layer_moves[current_layer].append(current_coordinate.copy())

        # Remove layers without extrude move
        for key in list(extrude_layer_moves.keys()):
            if len(extrude_layer_moves[key]) == 0:
                extrude_layer_moves.pop(key)
        return extrude_layer_moves

    def get_layer_min_max_before_fade(self, extrude_layer_moves, fade_end=0):
        layer_min_max_list = list()

        # Not defined, then we are going to analyse all layers
        if fade_end == 0:
            fade_end = float('inf')

        for layer_height in extrude_layer_moves:
            if layer_height < fade_end:

                mesh_min, mesh_max = self.get_move_min_max(extrude_layer_moves[layer_height])
                layer_min_max_list.append(mesh_min)
                layer_min_max_list.append(mesh_max)

        # Calculate overall min max
        mesh_min, mesh_max = self.get_polygon_min_max(layer_min_max_list)

        return mesh_min, mesh_max

    def get_move_min_max(self, move_vertices):
        x_min, x_max, y_min, y_max = float('inf'), 0, float('inf'), 0

        for pt in move_vertices:
            x = pt['X']
            y = pt['Y']

            x_min = min(x_min, x)
            x_max = max(x_max, x)

            y_min = min(y_min, y)
            y_max = max(y_max, y)

        return (x_min, y_min), (x_max, y_max)

    def get_polygon_min_max(self, polygon):
        x_min, x_max, y_min, y_max = float('inf'), 0, float('inf'), 0

        for pt in polygon:
            x = pt[0]
            y = pt[1]

            x_min = min(x_min, x)
            x_max = max(x_max, x)

            y_min = min(y_min, y)
            y_max = max(y_max, y)

        return (x_min, y_min), (x_max, y_max)

    def apply_min_max_margin(self, mesh_min, mesh_max):
        # Apply margin
        mesh_min = (mesh_min[0] - self.mesh_area_clearance, mesh_min[1] - self.mesh_area_clearance)
        mesh_max = (mesh_max[0] + self.mesh_area_clearance, mesh_max[1] + self.mesh_area_clearance)

        return mesh_min, mesh_max

    def apply_probe_point_limits(self, num_horizontal_probes, num_vertical_probes):
        # CHECK 1
        # Note that a mesh requires a minimum probe_count of 3 along each axis.
        # Reference: https://www.klipper3d.org/Bed_Mesh.html#basic-configuration
        num_horizontal_probes = int(max(self.minimum_axis_probe_counts, num_horizontal_probes))
        num_vertical_probes = int(max(self.minimum_axis_probe_counts, num_vertical_probes))

        # CHECK2
        # Reference: https://www.klipper3d.org/Bed_Mesh.html#mesh-interpolation
        # lagrange: Maximum 6 samples per axis
        if self.bed_mesh_config_algorithm == 'lagrange':
            num_horizontal_probes = int(min(6, num_horizontal_probes))
            num_vertical_probes = int(min(6, num_vertical_probes))

        # bicubic: If the minimum count < 4 AND maximum count > 6 then we bump the minimum count to 4
        elif self.bed_mesh_config_algorithm == 'bicubic':
            min_probe_cnt = min(num_horizontal_probes, num_vertical_probes)
            max_probe_cnt = max(num_horizontal_probes, num_vertical_probes)
            if min_probe_cnt < 4 and max_probe_cnt > 6:
                num_horizontal_probes = int(max(4, num_horizontal_probes))
                num_vertical_probes = int(max(4, num_vertical_probes))

        else:
            raise ValueError("Invalid/unknown bed_mesh algorithm {}".format(self.bed_mesh_config_algorithm))

        return num_horizontal_probes, num_vertical_probes

    def get_probe_points(self, mesh_min, mesh_max):
        horizontal_distance = mesh_max[0] - mesh_min[0]
        vertical_distance = mesh_max[1] - mesh_min[1]

        # Generate expected number of points
        num_horizontal_probes = math.ceil(horizontal_distance / self.max_probe_horizontal_distance)
        num_vertical_probes = math.ceil(vertical_distance / self.max_probe_vertical_distance)

        # Apply limits to the number of points subject to the minimum points, as well as algorithm
        num_horizontal_probes, num_vertical_probes = self.apply_probe_point_limits(num_horizontal_probes, num_vertical_probes)

        # Generate probe coordinates
        horizontal_probe_points = numpy.linspace(mesh_min[0], mesh_max[0], num_horizontal_probes)
        vertical_probe_points = numpy.linspace(mesh_min[1], mesh_max[1], num_vertical_probes)

        probe_coordinates = []
        for y_idx in range(len(vertical_probe_points)):
            y_coord = vertical_probe_points[y_idx]

            if is_even(y_idx):
                for x_coord in horizontal_probe_points:
                    probe_coordinates.append((x_coord, y_coord))
            else:
                for x_coord in reversed(horizontal_probe_points):
                    probe_coordinates.append((x_coord, y_coord))

        relative_reference_index = int(round((num_horizontal_probes * num_vertical_probes) / 2))

        return (num_horizontal_probes, num_vertical_probes), probe_coordinates, relative_reference_index


def is_even(number):
    if number % 2 == 0:
        return True
    else:
        return False



def load_config(config):
    return AdaptiveBedMesh(config)



if __name__ == '__main__':
    pass
    from matplotlib import pyplot as plt

    # # gcode_file = r'C:\Users\rba90\Downloads\g-all.gcode'
    # # gcode_file = r'C:\Users\rba90\Downloads\leg2.gcode'
    # # gcode_file = r'C:\Users\rba90\Downloads\V350_demo.gcode'
    # # gcode_file = r'C:\Users\Ran Bao\Downloads\OrcaCube_PLA_34m48s.gcode'
    # # gcode_file = r'C:\Users\Ran Bao\Downloads\VaseShape-Cylinder-Voron 0.1-PLA+.gcode'
    # gcode_file = r'C:\Users\Ran Bao\Downloads\G2_Cylinder_PLA_12s.gcode'
    # # gcode_file = r'C:\Users\Ran Bao\Downloads\Cylinder_PLA_12s.gcode'
    # gcode_file = r'C:\Users\Ran Bao\Downloads\mygcode.txt'
    #
    # bed_mesh = AdaptiveBedMesh()
    # bed_mesh.extract_first_layer_from_gcode_file(gcode_file)
    # bed_mesh.get_min_max_square()
    #
    # fig = plt.figure()
    # ax = fig.subplots()
    #
    # x_moves = []
    # y_moves = []
    # for move in bed_mesh._first_layer_move_vertices:
    #     x_moves.append(move['X'])
    #     y_moves.append(move['Y'])
    #
    # ax.plot(x_moves, y_moves)
    #
    # (x_min, x_max), (y_min, y_max) = bed_mesh.get_min_max_square()
    #
    # probe_points, zero_reference_position = bed_mesh.get_probe_points()
    # probe_points_x, probe_points_y = zip(*probe_points)
    #
    # ax.plot([x_min, x_min, x_max, x_max, x_min], [y_min, y_max, y_max, y_min, y_min], label='Print Boundary')
    #
    # ax.plot(probe_points_x, probe_points_y, marker='x', linestyle='--', label='Probe points')
    # ax.scatter(zero_reference_position[0], zero_reference_position[1], marker='o', label='Zero Reference Point')
    #
    # ax.legend(*ax.get_legend_handles_labels())
    # plt.show()
