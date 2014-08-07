import math
from tool_operation import ToolOperation, TOEnum
from tool_abstract_follow import TOAbstractFollow
from generalized_setting import TOSetting

import cairo
import json

class TOExactFollow(TOAbstractFollow):
    def __init__(self, state, depth=0, index=0, data=None):
        self.state = state
        super(TOAbstractFollow, self).__init__(state)
        self.name = TOEnum.exact_follow
        if data == None:
            self.depth = depth
            self.index = index
            self.path = None
        else:
            self.deserialize(data)
        self.display_name = TOEnum.exact_follow+" "+str(self.index)

    def serialize(self):
        return {'type': 'toexactfollow', 'path_ref': self.path.name, 'depth': self.depth, 'index': self.index}

    def deserialize(self, data):
        self.depth = data["depth"]
        self.index = data["index"]
        p = self.try_load_path_by_name(data["path_ref"], self.state)
        if p:
            self.apply(p)

    def get_settings_list(self):
        settings_lst = [TOSetting("float", 0, self.state.settings.material.thickness, self.depth, "Depth, mm: ", self.set_depth_s),]
        return settings_lst

    def set_depth_s(self, setting):
        self.depth = setting.new_value

    def apply(self, path):
        if path.operations[self.name]:
            if path.ordered_elements!=None:
                print "setting path"
                self.path = path
                self.draw_list = path.ordered_elements
                return True
        return False

    def get_gcode(self):
        cp = self.tool.current_position
        out = ""
        new_pos = [cp[0], cp[1], self.tool.default_height]
        out+= self.state.settings.default_pp.move_to_rapid(new_pos)
        self.tool.current_position = new_pos

        start = self.path.ordered_elements[0].start

        new_pos = [start[0], start[1], new_pos[2]]
        out+= self.state.settings.default_pp.move_to_rapid(new_pos)
        self.tool.current_position = new_pos

        for step in range(int(self.depth/(self.tool.diameter/2.0))+1):
            for e in self.path.ordered_elements:
                out += self.process_el_to_gcode(e, step)

        new_pos = [new_pos[0], new_pos[1], self.tool.default_height]
        out+= self.state.settings.default_pp.move_to_rapid(new_pos)
        self.tool.current_position = new_pos
        return out

    def __repr__(self):
        return "<Exact follow>"
