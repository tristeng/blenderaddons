# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

bl_info = {
    "name": "Import Poliigon Texture",
    "author": "Tristen Georgiou",
    "version": (1, 0, 0),
    "blender": (2, 78, 0),
    "location": "File > Import > Poliigon Texture",
    "description": "Imports textures from Poliigon (https://www.poliigon.com)",
    "warning": "",
    "wiki_url": "",
    "category": "Import-Export",
}

import os.path
import glob
import bpy
from bpy_extras.image_utils import load_image


IMG_TYPES = ['COL', 'GLOSS', 'NRM', 'REFL', 'AO']


# -----------------------------------------------------------------------------
# Cycles utils
# borrowed from https://github.com/sambler/myblenderaddons/blob/master/io_import_images_as_planes.py
def get_input_nodes(node, nodes, links):
    # Get all links going to node.
    input_links = {lnk for lnk in links if lnk.to_node == node}
    # Sort those links, get their input nodes (and avoid doubles!).
    sorted_nodes = []
    done_nodes = set()
    for socket in node.inputs:
        done_links = set()
        for link in input_links:
            nd = link.from_node
            if nd in done_nodes:
                # Node already treated!
                done_links.add(link)
            elif link.to_socket == socket:
                sorted_nodes.append(nd)
                done_links.add(link)
                done_nodes.add(nd)
        input_links -= done_links
    return sorted_nodes


def auto_align_nodes(node_tree):
    print('\nAligning Nodes')
    x_gap = 200
    y_gap = 300
    nodes = node_tree.nodes
    links = node_tree.links
    to_node = None
    for node in nodes:
        if node.type == 'OUTPUT_MATERIAL':
            to_node = node
            break
    if not to_node:
        return  # Unlikely, but better check anyway...

    def align(to_node, nodes, links):
        from_nodes = get_input_nodes(to_node, nodes, links)
        for i, node in enumerate(from_nodes):
            node.location.x = to_node.location.x - x_gap
            node.location.y = to_node.location.y
            node.location.y -= i * y_gap
            node.location.y += (len(from_nodes)-1) * y_gap / (len(from_nodes))
            align(node, nodes, links)

    align(to_node, nodes, links)


def clean_node_tree(node_tree):
    nodes = node_tree.nodes
    for node in nodes:
        if not node.type == 'OUTPUT_MATERIAL':
            nodes.remove(node)
    return node_tree.nodes[0]


def get_images(path):
    imgs = {}
    for fn in glob.glob(os.path.join(path, '*.jpg')):
        for img_type in IMG_TYPES:
            if img_type not in imgs and img_type in fn:
                imgs[img_type] = load_image(fn)
    return imgs


def get_material_name(path):
    base = bpy.path.basename(path.rstrip('/\\'))
    index = base.rfind('_')
    if index > 0:
        return base[:index]
    return base


def create_poliigon_material(path):
    material = bpy.data.materials.new(name=get_material_name(path))
    material.use_nodes = True
    texture_nodes = {}
    images = get_images(path)
    node_tree = material.node_tree
    out_node = clean_node_tree(node_tree)
    # create image textures
    for img_type in IMG_TYPES:
        if img_type in images:
            tex = node_tree.nodes.new('ShaderNodeTexImage')
            tex.image = images[img_type]
            tex.label = img_type
            tex.color_space = 'NONE' if img_type not in ['COL', 'AO'] else 'COLOR'
            texture_nodes[img_type] = tex

    # create mix shader
    mix_shader = node_tree.nodes.new('ShaderNodeMixShader')
    node_tree.links.new(out_node.inputs[0], mix_shader.outputs[0])
    node_tree.links.new(texture_nodes['REFL'].outputs[0], mix_shader.inputs[0])
    
    # create diffuse node
    bsdf_diffuse = node_tree.nodes.new('ShaderNodeBsdfDiffuse')
    
    # create nodes for ambient occlusion, if it exists
    if 'AO' in texture_nodes:
        mix_rgb = node_tree.nodes.new('ShaderNodeMixRGB')
        mix_rgb.blend_type = 'MULTIPLY'
        mix_rgb.inputs[0].default_value = 0.8
        node_tree.links.new(mix_rgb.inputs[1], texture_nodes['COL'].outputs[0])
        node_tree.links.new(mix_rgb.inputs[2], texture_nodes['AO'].outputs[0])
        node_tree.links.new(bsdf_diffuse.inputs[0], mix_rgb.outputs[0])
    else:
        node_tree.links.new(bsdf_diffuse.inputs[0], texture_nodes['COL'].outputs[0])
    
    node_tree.links.new(bsdf_diffuse.outputs[0], mix_shader.inputs[1])
    
    # create glossy node
    bsdf_glossy = node_tree.nodes.new('ShaderNodeBsdfGlossy')
    node_tree.links.new(bsdf_glossy.inputs[1], texture_nodes['GLOSS'].outputs[0])
    node_tree.links.new(bsdf_glossy.outputs[0], mix_shader.inputs[2])
    
    # create normal map
    normal_map = node_tree.nodes.new('ShaderNodeNormalMap')
    node_tree.links.new(normal_map.inputs[1], texture_nodes['NRM'].outputs[0])
    node_tree.links.new(normal_map.outputs[0], bsdf_diffuse.inputs[2])
    node_tree.links.new(normal_map.outputs[0], bsdf_glossy.inputs[2])
    
    auto_align_nodes(node_tree)
    return material


class ImportPoliigonTextureOperator(bpy.types.Operator):
    """Poliigon texture importer"""
    bl_idname = "import.poliigon_texture"
    bl_label = "Import Poliigon Texture"

    filepath = bpy.props.StringProperty(subtype="DIR_PATH")

    def execute(self, context):
        path = self.properties.filepath
        if not os.path.isdir(path):
            msg = "Please select a directory not a file\n" + path
            self.report({'WARNING'}, msg)
            return
        
        create_poliigon_material(path)
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


def menu_func_import(self, context):
    self.layout.operator(
        ImportPoliigonTextureOperator.bl_idname, text="Import Poliigon Texture")


def register():
    bpy.utils.register_module(__name__)
    bpy.types.INFO_MT_file_import.append(menu_func_import)


def unregister():
    bpy.utils.unregister_module(__name__)
    bpy.types.INFO_MT_file_import.remove(menu_func_import)


if __name__ == "__main__":
    register()
