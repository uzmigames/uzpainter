#include "mesh/texturing_mesh.h"

#include <bit>
#include <cstring>
#include <string_view>

#include "uzp_core/manifest/sha256.h"

namespace uzp::mesh {

namespace {

static_assert(std::endian::native == std::endian::little, "the hash streams are little-endian");

/// SHA-256 over values appended in their little-endian byte form.
class Stream {
public:
    template <typename T>
    void Put(T value) {
        char bytes[sizeof(T)];
        std::memcpy(bytes, &value, sizeof(T));
        sha_.Update(std::string_view(bytes, sizeof(T)));
    }
    void PutText(std::string_view text) {
        sha_.Update(text);
        Put<std::uint8_t>(0);
    }
    std::string Hex() {
        static constexpr char kDigits[] = "0123456789abcdef";
        std::string hex;
        for (std::uint8_t byte : sha_.Finish()) {
            hex.push_back(kDigits[byte >> 4]);
            hex.push_back(kDigits[byte & 15]);
        }
        return hex;
    }

private:
    core::Sha256 sha_;
};

}  // namespace

std::size_t TexturingMesh::TriangleCount() const {
    std::size_t count = 0;
    for (const Object& object : objects) count += object.triangles.size();
    return count;
}

Hashes ComputeHashes(const TexturingMesh& mesh) {
    Hashes hashes;
    {
        Stream s;
        for (const Float3& p : mesh.positions) {
            s.Put(p.x);
            s.Put(p.y);
            s.Put(p.z);
        }
        for (const Object& object : mesh.objects) {
            for (double element : object.transform) s.Put(element);
        }
        hashes.positions = s.Hex();
    }
    {
        Stream s;
        for (const Corner& c : mesh.corners) {
            s.Put(c.uv0.u);
            s.Put(c.uv0.v);
        }
        hashes.uvs = s.Hex();
    }
    {
        Stream s;
        for (const Corner& c : mesh.corners) {
            s.Put(c.normal.x);
            s.Put(c.normal.y);
            s.Put(c.normal.z);
        }
        hashes.corner_normals = s.Hex();
    }
    {
        Stream s;
        for (const Object& object : mesh.objects) {
            s.Put(static_cast<std::uint32_t>(object.triangles.size()));
            for (const Triangle& t : object.triangles) {
                for (std::uint32_t corner : t.corners) s.Put(corner);
            }
        }
        for (const Corner& c : mesh.corners) s.Put(c.position);
        hashes.triangulation = s.Hex();
    }
    {
        Stream s;
        for (const Material& m : mesh.materials) {
            s.Put(m.index);
            s.PutText(m.name);
        }
        for (const Corner& c : mesh.corners) s.Put(c.material);
        hashes.materials = s.Hex();
    }
    return hashes;
}

core::json::Object HashesToJson(const Hashes& hashes) {
    return {
        {"corner_normals", hashes.corner_normals},
        {"materials", hashes.materials},
        {"positions", hashes.positions},
        {"triangulation", hashes.triangulation},
        {"uvs", hashes.uvs},
    };
}

}  // namespace uzp::mesh
