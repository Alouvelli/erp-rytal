export type Role = 'ADMIN' | 'SCOLARITE' | 'TEACHER' | 'STUDENT';

export interface User {
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  role: Role;
  avatar?: string;
  phone?: string;
}

export interface Class {
  id: string; name: string; level: string; specialty?: string; capacity: number; academicYear: string;
  _count?: { students: number };
}

export interface Subject {
  id: string; name: string; code: string; coefficient: number; hoursPerWeek?: number;
}

export interface Room {
  id: string; name: string; building?: string; capacity: number; type?: string;
}

export interface Teacher {
  id: string; userId: string; employeeId: string; department?: string; speciality?: string;
  user: Pick<User, 'firstName' | 'lastName'>;
}

export interface Student {
  id: string; userId: string; studentId: string; classId?: string; enrolledYear: number;
  user: Pick<User, 'firstName' | 'lastName'>;
  class?: Class;
}

export interface TimetableSlot {
  id: string; classId: string; teacherId: string; subjectId: string; roomId: string;
  dayOfWeek: number; startTime: string; endTime: string; semester: number; weekType?: string;
  class: Class; teacher: Teacher; subject: Subject; room: Room;
}

export interface AttendanceSheet {
  id: string; timetableSlotId: string; teacherId: string; sessionDate: string;
  status: 'PENDING' | 'SIGNED' | 'APPROVED' | 'REJECTED';
  signedAt?: string; validatedAt?: string; validatedBy?: string; remarks?: string;
  teacher: Teacher; timetableSlot: TimetableSlot;
}

export interface Evaluation {
  id: string; subjectId: string; classId: string;
  type: 'CC' | 'TP' | 'EXAM' | 'RATTRAPAGE' | 'DEVOIR';
  name: string; date: string; maxScore: number; weight: number; semester: number;
  subject: Subject; grades?: Grade[];
}

export interface Grade {
  id: string; studentId: string; evaluationId: string; score?: number;
  isAbsent: boolean; comment?: string; publishedAt?: string;
  student: Student; evaluation: Evaluation;
}

export interface StudentAbsence {
  id: string; studentId: string; timetableSlotId: string; sessionDate: string;
  status: 'UNJUSTIFIED' | 'PENDING' | 'JUSTIFIED';
  justification?: string; documentPath?: string;
  student: Student; timetableSlot: TimetableSlot;
}

export interface CourseCancellation {
  id: string; timetableSlotId: string; teacherId: string; sessionDate: string;
  reason: string; status: 'PENDING' | 'APPROVED' | 'REJECTED';
  rescheduledDate?: string; rescheduledRoom?: string;
  teacher: Teacher; timetableSlot: TimetableSlot;
}

export interface Notification {
  id: string; userId: string; type: string; title: string; message: string;
  isRead: boolean; createdAt: string;
}

export interface DashboardStats {
  totalStudents: number; totalTeachers: number; totalClasses: number;
  pendingAttendance: number; pendingCancellations: number; weeklyAbsences: number;
}
