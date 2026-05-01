"""{{display_name}} - Maya Python plugin skeleton."""

import maya.api.OpenMaya as om


def maya_useNewAPI():
    pass


PLUGIN_NAME = "{{name}}"


class HelloCmd(om.MPxCommand):
    kPluginCmdName = PLUGIN_NAME

    @staticmethod
    def creator():
        return HelloCmd()

    def doIt(self, args):
        self.setResult("[{{name}}] hello from {{display_name}} v{{version}}")


def initializePlugin(plugin):
    fn = om.MFnPlugin(plugin, "{{author}}", "{{version}}", "Any")
    fn.registerCommand(HelloCmd.kPluginCmdName, HelloCmd.creator)


def uninitializePlugin(plugin):
    fn = om.MFnPlugin(plugin)
    fn.deregisterCommand(HelloCmd.kPluginCmdName)
