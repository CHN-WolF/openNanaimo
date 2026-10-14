using System.Buffers.Binary;
using System.Collections;
using System.Text;
using OpenNanaimo.Adapter.Models;
using OpenNanaimo.Adapter.Services;

internal static partial class Program
{
    private static byte[] MentorApplication(string name, uint uid)
    {
        var payload = new byte[24]; payload[0] = 1;
        BinaryPrimitives.WriteUInt32LittleEndian(payload.AsSpan(4), uid);
        Encoding.GetEncoding(936).GetBytes(name).CopyTo(payload, 8);
        return payload;
    }

    private static async Task CheckGraduationProjectionAsync()
    {
        await using var f = await Fixture.CreateAsync();
        f.Service.MentorshipRules = MentorshipPolicy.Production;
        Check((await Dispatch(f, f.Teacher, 0xC578, []))![260] == 0,
            "teacher without graduates has a zero graduate counter");
        var request = await f.Service.RequestMentorshipAsync(Id(f.Teacher), Character(f.Student).Id,
            MentorshipDirection.TeacherInvitation);
        Check((await f.Service.RespondMentorshipAsync(Id(f.Student), request.Request!.Id, true)).Success,
            "graduation projection relation established");
        await f.ExecuteAsync("UPDATE Characters SET Level=20,Experience=$exp WHERE Id=$id",
            ("$exp", CharacterProgression.ExperienceRequiredForLevel(20)), ("$id", Character(f.Student).Id));
        // The persistent level, not the stale in-memory level, owns graduation.
        var frame = (await Dispatch(f, f.Teacher, 0xC578, []))!;
        Check(frame.Length == 288 && frame[260] == 1,
            "C579 fills frame+260 consumed by the teacher graduate counter");
        Check(BinaryPrimitives.ReadUInt32LittleEndian(frame.AsSpan(264)) == 1,
            "graduated relationship remains in the ten-row profile");
        Check((await f.Database.GetMentorshipProfileAsync(Character(f.Teacher).Id)).Graduates == 1,
            "graduate counter agrees with persistent distinct-student total");
        await Dispatch(f, f.Teacher, 0xC578, []);
        Check(await f.ScalarAsync("SELECT COUNT(*) FROM MentorshipGraduations") == 1,
            "graduate display refresh does not duplicate graduation receipts");
        Check(await f.ScalarAsync("SELECT COUNT(*) FROM MentorshipGraduationAwards") == 0,
            "level-only graduation does not invent coursework rewards");
        await Dispatch(f, f.Teacher, 0xC57F, []);
        var list = (await Dispatch(f, f.Other, 0xC57D, new byte[4]))!;
        Check(BinaryPrimitives.ReadUInt16LittleEndian(list.AsSpan(18)) == 1,
            "advertisement and relationship page publish the same graduate total");
        for (var i = 0; i < 10; i++)
        {
            var historical = await f.CreateSessionAsync("history" + i, "History" + i, 20, 1);
            await f.ExecuteAsync("INSERT INTO MentorshipRelations(TeacherCharacterId,StudentCharacterId,State,CreatedAt,EndedAt) "
                + "VALUES($teacher,$student,1,$date,$date)", ("$teacher", Character(f.Teacher).Id),
                ("$student", Character(historical).Id), ("$date", DateTime.UtcNow.ToString("O")));
        }
        // Historic duplicate relationships must not inflate distinct graduate totals.
        await f.ExecuteAsync("INSERT INTO MentorshipRelations(TeacherCharacterId,StudentCharacterId,State,CreatedAt,EndedAt) "
            + "VALUES($teacher,$student,1,$date,$date)", ("$teacher", Character(f.Teacher).Id),
            ("$student", Character(f.Student).Id), ("$date", DateTime.UtcNow.ToString("O")));
        frame = (await Dispatch(f, f.Teacher, 0xC578, []))!;
        Check(frame[260] == 11 && BinaryPrimitives.ReadUInt32LittleEndian(frame.AsSpan(264)) == 10,
            "graduate total is distinct and independent of the ten-row display limit");
    }

    private static async Task CheckAdvertisementApplicationsAsync()
    {
        // Cover non-scene identity values and the no-identity sentinel.
        foreach (var uid in new[] { 0x3F800000u, 0x3D4CCCC8u, uint.MaxValue })
        {
            await using var f = await Fixture.CreateAsync();
            f.Service.MentorshipRules = MentorshipPolicy.Production;
            await Dispatch(f, f.Teacher, 0xC57F, []);
            var teacher = Character(f.Teacher); var student = Character(f.Student);
            var pending = (IList)Get(f.Student, "PendingBroadcasts")!; pending.Clear();
            Check(await Dispatch(f, f.Student, 0xC576, MentorApplication(teacher.Name, uid)) is null
                && pending.Count == 1, "advertisement name routes application with non-scene ID " + uid.ToString("X8"));
            Check((string)Get(Get(pending[0]!, "Target")!, "SessionId")! == Id(f.Teacher),
                "advertisement application targets the teacher session only");
            var notice = (byte[])Get(pending[0]!, "Payload")!;
            Check(notice.Length == 24 && notice[0] == 0 && notice[1] == 0
                && BinaryPrimitives.ReadUInt32LittleEndian(notice.AsSpan(4)) == WireIdentityAllocator.GetSceneEntityId(student.Id),
                "relayed application contains the authoritative student scene identity");
            Check(Encoding.GetEncoding(936).GetString(notice, 8, 16).TrimEnd('\0') == student.Name,
                "relayed application names the applicant rather than the advertiser");
            var response = new byte[24]; response[0] = 10;
            BinaryPrimitives.WriteUInt16LittleEndian(response.AsSpan(6), WireIdentityAllocator.GetSceneEntityId(student.Id));
            Check((await Dispatch(f, f.Teacher, 0xC577, response)) is { Length: 32 },
                "advertised teacher accepts the request with the native response");
            Check((await f.Database.GetMentorshipRelationsAsync(Actor(f.Student))).Single().TeacherCharacterId == teacher.Id,
                "advertisement acceptance persists the intended teacher");
        }
        await using var invalid = await Fixture.CreateAsync();
        invalid.Service.MentorshipRules = MentorshipPolicy.Production;
        var broadcasts = (IList)Get(invalid.Student, "PendingBroadcasts")!;
        async Task Reject(string name, uint uid, string description)
        {
            broadcasts.Clear();
            Check(await Dispatch(invalid, invalid.Student, 0xC576, MentorApplication(name, uid)) is null
                && broadcasts.Count == 0, description);
        }
        await Reject(Character(invalid.Teacher).Name, 0x3F800000, "name fallback rejects a non-advertising target");
        await Dispatch(invalid, invalid.Teacher, 0xC57F, []);
        await Reject("MissingTeacher", 0x3F800000, "name fallback rejects a nonexistent advertisement");
        await Reject(Character(invalid.Teacher).Name, WireIdentityAllocator.GetSceneEntityId(Character(invalid.Other).Id),
            "valid but mismatched scene identity cannot override the advertised name");
        Set(invalid.Teacher, "ChannelId", 2);
        await Reject(Character(invalid.Teacher).Name, 0x3F800000, "advertisement fallback cannot cross channels");
        Set(invalid.Teacher, "ChannelId", 1);
        Set(invalid.Teacher, "TownSceneActive", false);
        await Reject(Character(invalid.Teacher).Name, 0x3F800000, "advertisement fallback cannot enter a non-town session");
        Set(invalid.Teacher, "TownSceneActive", true);
        Set(invalid.Teacher, "DungeonRoomId", 1);
        await Reject(Character(invalid.Teacher).Name, 0x3F800000, "advertisement fallback rejects a retained dungeon room");
        Set(invalid.Teacher, "DungeonRoomId", 0);
        broadcasts.Clear();
        var malformed = MentorApplication(Character(invalid.Teacher).Name, 0x3F800000);
        malformed[8] = 1;
        Check(await Dispatch(invalid, invalid.Student, 0xC576, malformed) is null && broadcasts.Count == 0,
            "malformed advertisement names cannot route applications");
        await Dispatch(invalid, invalid.Teacher, 0xC581, []);
        await Reject(Character(invalid.Teacher).Name, 0x3F800000, "stopped advertisement is not a name-routing authority");
        await Dispatch(invalid, invalid.Teacher, 0xC57F, []);
        invalid.RemovePresence(invalid.Teacher);
        await Reject(Character(invalid.Teacher).Name, 0x3F800000, "offline advertisement owner receives no request");
        Check(await invalid.ScalarAsync("SELECT COUNT(*) FROM MentorshipRequests") == 0,
            "rejected applications create no durable pending request");
    }
}
