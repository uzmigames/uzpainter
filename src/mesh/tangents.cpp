#include "mesh/tangents.h"

#include <mikktspace.h>

#include <new>

namespace uzp::mesh {

namespace {

/// One object of the mesh as MikkTSpace sees it: its triangles are the faces, in order.
struct ObjectFaces {
    TexturingMesh* mesh;
    const Object* object;

    const Corner& At(int face, int vert) const {
        return mesh->corners[object->triangles[static_cast<std::size_t>(face)].corners[static_cast<std::size_t>(vert)]];
    }
};

ObjectFaces& Faces(const SMikkTSpaceContext* context) { return *static_cast<ObjectFaces*>(context->m_pUserData); }

int NumFaces(const SMikkTSpaceContext* context) { return static_cast<int>(Faces(context).object->triangles.size()); }

int NumVerticesOfFace(const SMikkTSpaceContext*, const int) { return 3; }

void GetPosition(const SMikkTSpaceContext* context, float out[], const int face, const int vert) {
    const ObjectFaces& faces = Faces(context);
    const Float3& p = faces.mesh->positions[faces.At(face, vert).position];
    out[0] = p.x;
    out[1] = p.y;
    out[2] = p.z;
}

void GetNormal(const SMikkTSpaceContext* context, float out[], const int face, const int vert) {
    const Float3& n = Faces(context).At(face, vert).normal;
    out[0] = n.x;
    out[1] = n.y;
    out[2] = n.z;
}

void GetTexCoord(const SMikkTSpaceContext* context, float out[], const int face, const int vert) {
    const Float2& uv = Faces(context).At(face, vert).uv0;
    out[0] = uv.u;
    out[1] = uv.v;
}

void SetTSpaceBasic(const SMikkTSpaceContext* context, const float tangent[], const float sign, const int face,
                    const int vert) {
    ObjectFaces& faces = Faces(context);
    const std::uint32_t corner =
        faces.object->triangles[static_cast<std::size_t>(face)].corners[static_cast<std::size_t>(vert)];
    faces.mesh->corners[corner].tangent = {tangent[0], tangent[1], tangent[2], sign};
}

}  // namespace

void ComputeTangents(TexturingMesh& mesh) {
    for (Corner& c : mesh.corners) c.tangent = {};
    SMikkTSpaceInterface callbacks{};
    callbacks.m_getNumFaces = NumFaces;
    callbacks.m_getNumVerticesOfFace = NumVerticesOfFace;
    callbacks.m_getPosition = GetPosition;
    callbacks.m_getNormal = GetNormal;
    callbacks.m_getTexCoord = GetTexCoord;
    callbacks.m_setTSpaceBasic = SetTSpaceBasic;
    for (const Object& object : mesh.objects) {
        if (object.triangles.empty()) continue;
        ObjectFaces faces{&mesh, &object};
        SMikkTSpaceContext context{&callbacks, &faces};
        // genTangSpaceDefault fails only when it cannot allocate its work arrays.
        if (genTangSpaceDefault(&context) == 0) throw std::bad_alloc();
    }
}

Frame InterpolateFrame(const TexturingMesh& mesh, const Triangle& triangle, const std::array<float, 3>& weights,
                       core::TangentSpace mode) {
    const std::array<Corner, 3> corners = {mesh.corners[triangle.corners[0]], mesh.corners[triangle.corners[1]],
                                         mesh.corners[triangle.corners[2]]};
    return InterpolateFrame(corners, weights, mode);
}

Frame InterpolateFrame(const std::array<Corner, 3>& corners, const std::array<float, 3>& weights,
                       core::TangentSpace mode) {
    using namespace v3;
    Frame frame{};
    float sign = 0.0f;
    for (std::size_t i = 0; i < 3; ++i) {
        const Corner& c = corners[i];
        const Float3 t = CornerTangent(c);
        frame.t = Add(frame.t, Scale(t, weights[i]));
        frame.n = Add(frame.n, Scale(c.normal, weights[i]));
        sign += weights[i] * c.tangent[3];
        if (mode == core::TangentSpace::PerVertex) {
            const Float3 corner = Scale(Cross(c.normal, t), c.tangent[3]);
            frame.b = Add(frame.b, Scale(corner, weights[i]));
        }
    }
    if (mode == core::TangentSpace::PerFragment) frame.b = Scale(Cross(frame.n, frame.t), sign < 0 ? -1.0f : 1.0f);
    return frame;
}

Float3 ToTangentSpace(const Frame& f, const Float3& normal) {
    using namespace v3;
    // The rows of the inverse of [vT vB vN] times its determinant; the sign keeps the result in
    // the frame's own orientation.
    const Float3 row0 = Cross(f.b, f.n);
    const Float3 row1 = Cross(f.n, f.t);
    const Float3 row2 = Cross(f.t, f.b);
    const float sign = Dot(f.t, row0) < 0 ? -1.0f : 1.0f;
    return Normalize(Scale({Dot(normal, row0), Dot(normal, row1), Dot(normal, row2)}, sign));
}

Float3 FromTangentSpace(const Frame& f, const Float3& t) {
    using namespace v3;
    return Normalize(Add(Add(Scale(f.t, t.x), Scale(f.b, t.y)), Scale(f.n, t.z)));
}

}  // namespace uzp::mesh
