__all__ = [
    'VoxelizePoints',
]

import numpy as np
import vtk
from vtk.util import keys
from vtk.util import numpy_support as nps
from vtk.numpy_interface import dataset_adapter as dsa

from ..base import PVGeoAlgorithmBase
from .. import _helpers
from ..version import checkNumpy
from .xyz import RotationTool

###############################################################################


class VoxelizePoints(PVGeoAlgorithmBase):
    """This makes a vtkUnstructuredGrid of scattered points given voxel sizes as input arrays.
    This assumes that the data is at least 2-Dimensional on the XY Plane."""
    def __init__(self):
        PVGeoAlgorithmBase.__init__(self,
            nInputPorts=1, inputType='vtkPolyData',
            nOutputPorts=1, outputType='vtkUnstructuredGrid')
        self.__dx = None
        self.__dy = None
        self.__dz = None
        self.__estimateGrid = True
        self.__safe = 10.0

        # Not controlled by user:
        self.__angle = 0.0



    def AddFieldData(self, grid):
        # Add angle
        a = vtk.vtkDoubleArray()
        a.SetName('Recovered Angle (Deg.)')
        a.SetNumberOfValues(1)
        a.SetValue(0, np.rad2deg(self.__angle))
        grid.GetFieldData().AddArray(a)
        # Add cell sizes
        s = vtk.vtkDoubleArray()
        s.SetName('Recovered Cell Sizes')
        s.SetNumberOfComponents(3)
        s.InsertNextTuple3(self.__dx, self.__dy, self.__dz)
        grid.GetFieldData().AddArray(s)
        return grid

    @staticmethod
    def AddCellData(grid, arr, name):
        c = nps.numpy_to_vtk(num_array=arr, deep=True)
        c.SetName(name)
        grid.GetCellData().AddArray(c)
        return grid


    def EstimateUniformSpacing(self, x, y, z):
        """
        This assumes that the input points make up some sort of uniformly spaced
        grid. If those points do not vary along a specified axis, then use
        (dx,dy,dz) args to set a default spacing. Otherwise nonvarying axis spacings
        will be determined by other axii.
        """
        # TODO: implement ability to rotate around Z axis (think PoroTomo vs UTM)
        # TODO: implement way to estimate rotation
        assert(len(x) == len(y) == len(z))
        num = len(x)
        if num == 1:
            # Only one point.. use safe
            return x, y, z, self.__safe, self.__safe, self.__safe, 0.0

        r = RotationTool()
        xr, yr, zr, dx, dy, angle = r.EstimateAndRotate(x, y, z)
        self.__angle = angle
        uz = np.diff(np.unique(z))
        if len(uz) > 0: dz = np.average(uz)
        else: dz = self.__safe
        self.__dx = dx
        self.__dy = dy
        self.__dz = dz
        return xr, yr, zr


    def PointsToGrid(self, xo,yo,zo, dx,dy,dz, grid=None):
        if not checkNumpy():
            raise RuntimeError("`VoxelizePoints` cannot work with versions of NumPy below 1.10.x . You must update NumPy.")
            return None
        if grid is None:
            grid = vtk.vtkUnstructuredGrid()


        if self.__estimateGrid:
            x,y,z = self.EstimateUniformSpacing(xo, yo, zo)
        else:
            x,y,z = xo, yo, zo

        dx,dy,dz = self.__dx, self.__dy, self.__dz

        numCells = len(x)

        # Generate cell nodes for all points in data set
        #- Bottom
        c_n1 = np.stack( ((x - dx/2) , (y - dy/2), (z - dz/2) ), axis=1)
        c_n2 = np.stack(( (x + dx/2) , (y - dy/2), (z - dz/2) ), axis=1)
        c_n3 = np.stack(( (x - dx/2) , (y + dy/2), (z - dz/2) ), axis=1)
        c_n4 = np.stack(( (x + dx/2) , (y + dy/2), (z - dz/2) ), axis=1)
        #- Top
        c_n5 = np.stack(( (x - dx/2) , (y - dy/2), (z + dz/2) ), axis=1)
        c_n6 = np.stack(( (x + dx/2) , (y - dy/2), (z + dz/2) ), axis=1)
        c_n7 = np.stack(( (x - dx/2) , (y + dy/2), (z + dz/2) ), axis=1)
        c_n8 = np.stack(( (x + dx/2) , (y + dy/2), (z + dz/2) ), axis=1)

        #- Concatenate
        all_nodes = np.concatenate((
            c_n1,
            c_n2,
            c_n3,
            c_n4,
            c_n5,
            c_n6,
            c_n7,
            c_n8), axis=0)

        # Search for unique nodes and use the min cell size as the tolerance
        TOLERANCE = np.min([dx, dy]) / 2.0
        # Round XY plane by the tolerance
        txy = np.around(all_nodes[:,0:2]/TOLERANCE)
        all_nodes[:,0:2] = txy
        unique_nodes, ind_nodes = np.unique(all_nodes, return_inverse=True, axis=0)
        unique_nodes[:,0:2] *= TOLERANCE
        numPts = len(unique_nodes)

        # Make the cells
        pts = vtk.vtkPoints()
        cells = vtk.vtkCellArray()

        # insert unique nodes as points
        if self.__estimateGrid:
            unique_nodes[:,0:2] = RotationTool.Rotate(unique_nodes[:,0:2], -self.__angle)
            self.AddFieldData(grid)

        for i in range(numPts):
            # for each node
            pts.InsertPoint(i,
                unique_nodes[i,0], unique_nodes[i,1], unique_nodes[i,2]
            )

        cnt = 0
        arridx = np.zeros(numCells)
        for i in range(numCells):
            vox = vtk.vtkVoxel()
            for j in range(8):
                vox.GetPointIds().SetId(j, ind_nodes[j*numCells + i])
            cells.InsertNextCell(vox)

            arridx[i] = i
            cnt += 8

        grid.SetPoints(pts)
        grid.SetCells(vtk.VTK_VOXEL, cells)
        #VoxelizePoints.AddCellData(grid, arridx, 'Voxel ID') # For testing
        return grid

    @staticmethod
    def PointsToGridWrapper(grid, tup):
        """tup = (x,dx,y,dy,z,dz)"""
        x, dx, y, dy, z, dz = tup
        return VoxelizePoints.PointsToGrid(x, y, z, dx, dy, dz, grid=grid)

    def _CopyArrays(self, pdi, pdo):
        for i in range(pdi.GetPointData().GetNumberOfArrays()):
            arr = pdi.GetPointData().GetArray(i)
            _helpers.addArray(pdo, 1, arr) # adds to CELL data
        return pdo

    def RequestData(self, request, inInfoVec, outInfoVec):
        # Get input/output of Proxy
        pdi = self.GetInputData(inInfoVec, 0, 0)
        pdo = self.GetOutputData(outInfoVec, 0)
        # Perfrom task
        wpdi = dsa.WrapDataObject(pdi)
        pts = wpdi.Points
        x, y, z = pts[:,0], pts[:,1], pts[:,2]
        self.PointsToGrid(x, y, z,
            self.__dx, self.__dy, self.__dz, grid=pdo)
        # Now append data to grid
        self._CopyArrays(pdi, pdo)
        return 1


    #### Seters and Geters ####


    def SetSafeSize(self, safe):
        if self.__safe != safe:
            self.__safe = safe
            self.Modified()

    def SetDeltaX(self, dx):
        self.__dx = dx
        self.Modified()

    def SetDeltaY(self, dy):
        self.__dy = dy
        self.Modified()

    def SetDeltaZ(self, dz):
        self.__dz = dz
        self.SetSafeSize(dz)
        self.Modified()

    def SetDeltas(self, dx, dy, dz):
        self.SetDeltaX(dx)
        self.SetDeltaY(dy)
        self.SetDeltaZ(dz)

    def SetEstimateGrid(self, flag):
        if self.__estimateGrid != flag:
            self.__estimateGrid = flag
            self.Modified()





###############################################################################
