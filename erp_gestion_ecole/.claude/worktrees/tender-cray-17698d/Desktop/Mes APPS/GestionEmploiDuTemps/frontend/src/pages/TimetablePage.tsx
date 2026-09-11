import { useEffect, useState } from 'react';
import { timetableApi, classApi, teacherApi, subjectApi, roomApi } from '../services/api';
import { TimetableSlot, Class, Subject, Room } from '../types';
import { useAuth } from '../context/AuthContext';
import { PlusIcon, TrashIcon } from '@heroicons/react/24/outline';
import { useForm } from 'react-hook-form';
import toast from 'react-hot-toast';
import clsx from 'clsx';

const DAYS = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi'];
const HOURS = ['08:00','09:00','10:00','11:00','12:00','13:00','14:00','15:00','16:00','17:00','18:00'];
const COLORS = ['bg-blue-100 border-blue-300 text-blue-800', 'bg-purple-100 border-purple-300 text-purple-800',
  'bg-green-100 border-green-300 text-green-800', 'bg-orange-100 border-orange-300 text-orange-800',
  'bg-pink-100 border-pink-300 text-pink-800', 'bg-teal-100 border-teal-300 text-teal-800'];

export default function TimetablePage() {
  const { user } = useAuth();
  const [slots, setSlots] = useState<TimetableSlot[]>([]);
  const [classes, setClasses] = useState<Class[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [teachers, setTeachers] = useState<any[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [filterClass, setFilterClass] = useState('');
  const [filterSemester, setFilterSemester] = useState('1');
  const { register, handleSubmit, reset } = useForm();

  const canEdit = user?.role === 'ADMIN' || user?.role === 'SCOLARITE';

  const load = () => {
    const params: any = { semester: filterSemester };
    if (filterClass) params.classId = filterClass;
    timetableApi.getAll(params).then(({ data }) => setSlots(data.data));
  };

  useEffect(() => {
    load();
    classApi.getAll().then(({ data }) => setClasses(data.data));
    subjectApi.getAll().then(({ data }) => setSubjects(data.data));
    roomApi.getAll().then(({ data }) => setRooms(data.data));
    import('../services/api').then(m => m.userApi.getAll().then(({ data }) => setTeachers(data.data.filter((u: any) => u.role === 'TEACHER'))));
  }, [filterClass, filterSemester]);

  const onSubmit = async (data: any) => {
    try {
      await timetableApi.create(data);
      toast.success('Créneau créé avec succès');
      setShowModal(false); reset(); load();
    } catch (e: any) {
      toast.error(e.response?.data?.message || 'Erreur');
    }
  };

  const deleteSlot = async (id: string) => {
    if (!confirm('Supprimer ce créneau ?')) return;
    await timetableApi.delete(id);
    toast.success('Créneau supprimé');
    load();
  };

  const subjectColorMap = new Map<string, string>();
  let colorIdx = 0;
  slots.forEach(s => { if (!subjectColorMap.has(s.subjectId)) subjectColorMap.set(s.subjectId, COLORS[colorIdx++ % COLORS.length]); });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Emploi du temps</h1>
          <p className="text-gray-500 text-sm mt-1">Vue hebdomadaire par classe</p>
        </div>
        {canEdit && (
          <button onClick={() => setShowModal(true)} className="btn-primary">
            <PlusIcon className="w-4 h-4" /> Ajouter un créneau
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="card p-4 flex flex-wrap gap-3">
        <select className="input w-auto" value={filterClass} onChange={e => setFilterClass(e.target.value)}>
          <option value="">Toutes les classes</option>
          {classes.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select className="input w-auto" value={filterSemester} onChange={e => setFilterSemester(e.target.value)}>
          <option value="1">Semestre 1</option>
          <option value="2">Semestre 2</option>
        </select>
      </div>

      {/* Calendar grid */}
      <div className="card overflow-x-auto">
        <table className="w-full min-w-[700px]">
          <thead>
            <tr className="border-b border-gray-100 dark:border-gray-800">
              <th className="w-20 py-3 px-4 text-xs text-gray-500 font-medium text-left">Heure</th>
              {DAYS.map(d => (
                <th key={d} className="py-3 px-2 text-xs text-gray-700 dark:text-gray-300 font-semibold text-center">{d}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {HOURS.slice(0, -1).map((hour, hi) => (
              <tr key={hour} className="border-b border-gray-50 dark:border-gray-800/50">
                <td className="py-2 px-4 text-xs text-gray-400 align-top">{hour}</td>
                {DAYS.map((_, di) => {
                  const slot = slots.find(s => s.dayOfWeek === di && s.startTime === hour);
                  return (
                    <td key={di} className="py-1 px-1 align-top">
                      {slot && (
                        <div className={clsx('rounded-lg border p-2 text-xs group relative cursor-pointer', subjectColorMap.get(slot.subjectId))}>
                          <p className="font-semibold truncate">{slot.subject.name}</p>
                          <p className="truncate opacity-70">{slot.teacher.user.firstName} {slot.teacher.user.lastName}</p>
                          <p className="truncate opacity-70">{slot.room.name}</p>
                          {canEdit && (
                            <button onClick={() => deleteSlot(slot.id)}
                              className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 p-0.5 bg-red-500 text-white rounded">
                              <TrashIcon className="w-3 h-3" />
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="card w-full max-w-lg p-6">
            <h2 className="text-lg font-semibold mb-4">Nouveau créneau</h2>
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Classe</label>
                  <select className="input" {...register('classId', { required: true })}>
                    <option value="">Choisir...</option>
                    {classes.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Matière</label>
                  <select className="input" {...register('subjectId', { required: true })}>
                    <option value="">Choisir...</option>
                    {subjects.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Enseignant</label>
                  <select className="input" {...register('teacherId', { required: true })}>
                    <option value="">Choisir...</option>
                    {teachers.map(t => <option key={t.id} value={t.id}>{t.firstName} {t.lastName}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Salle</label>
                  <select className="input" {...register('roomId', { required: true })}>
                    <option value="">Choisir...</option>
                    {rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Jour</label>
                  <select className="input" {...register('dayOfWeek', { valueAsNumber: true, required: true })}>
                    {DAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Semestre</label>
                  <select className="input" {...register('semester', { valueAsNumber: true, required: true })}>
                    <option value={1}>Semestre 1</option>
                    <option value={2}>Semestre 2</option>
                  </select>
                </div>
                <div>
                  <label className="label">Début</label>
                  <select className="input" {...register('startTime', { required: true })}>
                    {HOURS.map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Fin</label>
                  <select className="input" {...register('endTime', { required: true })}>
                    {HOURS.slice(1).map(h => <option key={h} value={h}>{h}</option>)}
                  </select>
                </div>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1 justify-center">Créer</button>
                <button type="button" onClick={() => { setShowModal(false); reset(); }} className="btn-secondary flex-1 justify-center">Annuler</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
