import { PrismaClient, Role } from '@prisma/client';
import bcrypt from 'bcryptjs';

const prisma = new PrismaClient();

async function main() {
  console.log('🌱 Seeding database...');

  const hash = (p: string) => bcrypt.hash(p, 12);

  // Admin
  const adminUser = await prisma.user.upsert({
    where: { email: 'admin@universite.fr' },
    update: {},
    create: { email: 'admin@universite.fr', password: await hash('Admin@1234'), firstName: 'Super', lastName: 'Admin', role: Role.ADMIN },
  });

  // Scolarité
  const scolariteUser = await prisma.user.upsert({
    where: { email: 'scolarite@universite.fr' },
    update: {},
    create: { email: 'scolarite@universite.fr', password: await hash('Scol@1234'), firstName: 'Marie', lastName: 'Dupont', role: Role.SCOLARITE },
  });

  // Teachers
  const teacher1User = await prisma.user.upsert({
    where: { email: 'prof.martin@universite.fr' },
    update: {},
    create: { email: 'prof.martin@universite.fr', password: await hash('Prof@1234'), firstName: 'Jean', lastName: 'Martin', role: Role.TEACHER },
  });
  const teacher2User = await prisma.user.upsert({
    where: { email: 'prof.bernard@universite.fr' },
    update: {},
    create: { email: 'prof.bernard@universite.fr', password: await hash('Prof@1234'), firstName: 'Sophie', lastName: 'Bernard', role: Role.TEACHER },
  });

  const teacher1 = await prisma.teacher.upsert({
    where: { userId: teacher1User.id },
    update: {},
    create: { userId: teacher1User.id, employeeId: 'E001', department: 'Informatique', speciality: 'Développement Web' },
  });
  const teacher2 = await prisma.teacher.upsert({
    where: { userId: teacher2User.id },
    update: {},
    create: { userId: teacher2User.id, employeeId: 'E002', department: 'Mathématiques', speciality: 'Algèbre' },
  });

  // Classes
  const class1 = await prisma.class.upsert({
    where: { name: 'L3-INFO-A' },
    update: {},
    create: { name: 'L3-INFO-A', level: 'Licence 3', specialty: 'Informatique', capacity: 35, academicYear: '2024-2025' },
  });
  const class2 = await prisma.class.upsert({
    where: { name: 'M1-MATH-A' },
    update: {},
    create: { name: 'M1-MATH-A', level: 'Master 1', specialty: 'Mathématiques', capacity: 25, academicYear: '2024-2025' },
  });

  // Subjects
  const sub1 = await prisma.subject.upsert({ where: { code: 'INF301' }, update: {}, create: { name: 'Développement Web', code: 'INF301', coefficient: 3, hoursPerWeek: 4 } });
  const sub2 = await prisma.subject.upsert({ where: { code: 'INF302' }, update: {}, create: { name: 'Base de Données', code: 'INF302', coefficient: 3, hoursPerWeek: 3 } });
  const sub3 = await prisma.subject.upsert({ where: { code: 'MAT301' }, update: {}, create: { name: 'Algèbre Linéaire', code: 'MAT301', coefficient: 4, hoursPerWeek: 4 } });

  // Rooms
  const room1 = await prisma.room.upsert({ where: { name: 'Amphi A' }, update: {}, create: { name: 'Amphi A', building: 'Bâtiment A', capacity: 150, type: 'Amphithéâtre' } });
  const room2 = await prisma.room.upsert({ where: { name: 'TD-101' }, update: {}, create: { name: 'TD-101', building: 'Bâtiment B', capacity: 30, type: 'Salle TD' } });
  const room3 = await prisma.room.upsert({ where: { name: 'Info-Lab-1' }, update: {}, create: { name: 'Info-Lab-1', building: 'Bâtiment C', capacity: 25, type: 'Laboratoire' } });

  // Timetable slots
  const slot1 = await prisma.timetableSlot.create({
    data: { classId: class1.id, teacherId: teacher1.id, subjectId: sub1.id, roomId: room3.id, dayOfWeek: 0, startTime: '08:00', endTime: '10:00', semester: 1 },
  }).catch(() => null);

  const slot2 = await prisma.timetableSlot.create({
    data: { classId: class1.id, teacherId: teacher1.id, subjectId: sub2.id, roomId: room2.id, dayOfWeek: 1, startTime: '10:00', endTime: '12:00', semester: 1 },
  }).catch(() => null);

  const slot3 = await prisma.timetableSlot.create({
    data: { classId: class2.id, teacherId: teacher2.id, subjectId: sub3.id, roomId: room1.id, dayOfWeek: 2, startTime: '14:00', endTime: '16:00', semester: 1 },
  }).catch(() => null);

  // Students
  const students = [
    { email: 'alice.dupont@etu.fr', firstName: 'Alice', lastName: 'Dupont', studentId: 'ETU001' },
    { email: 'bob.martin@etu.fr', firstName: 'Bob', lastName: 'Martin', studentId: 'ETU002' },
    { email: 'clara.simon@etu.fr', firstName: 'Clara', lastName: 'Simon', studentId: 'ETU003' },
  ];

  for (const s of students) {
    const u = await prisma.user.upsert({
      where: { email: s.email },
      update: {},
      create: { email: s.email, password: await hash('Student@1234'), firstName: s.firstName, lastName: s.lastName, role: Role.STUDENT },
    });
    await prisma.student.upsert({
      where: { userId: u.id },
      update: {},
      create: { userId: u.id, studentId: s.studentId, classId: class1.id, enrolledYear: 2024 },
    });
  }

  // Evaluation
  const eval1 = await prisma.evaluation.create({
    data: { subjectId: sub1.id, classId: class1.id, type: 'CC', name: 'CC1 - Développement Web', date: new Date('2024-10-15'), maxScore: 20, weight: 1, semester: 1 },
  }).catch(() => null);

  console.log('✅ Seed terminé !');
  console.log('\n📋 Comptes créés :');
  console.log('  Admin    : admin@universite.fr / Admin@1234');
  console.log('  Scolarité: scolarite@universite.fr / Scol@1234');
  console.log('  Enseignant: prof.martin@universite.fr / Prof@1234');
  console.log('  Étudiant : alice.dupont@etu.fr / Student@1234');
}

main().catch(console.error).finally(() => prisma.$disconnect());
